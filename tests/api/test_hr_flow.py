"""HR API flow: job creation -> candidate approval gates -> screening ->
interview scheduling, plus HR employee-entitlement enforcement and
cross-tenant isolation of HR data.

Resume upload/AI processing is covered separately and thoroughly in
tests/workflows/test_resume_pipeline.py — here candidates are seeded
directly at the HR_REVIEW stage so this test focuses on the approval/
scheduling API surface, RBAC and audit trail instead of re-testing OCR/LLM
extraction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.models.candidate import (
    Candidate,
    CandidateIdentity,
    CandidateSource,
    CandidateStage,
)
from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.provisioning.models.provision import EmployeeProvision, ProvisionStatus
from app.ai_employees.registry.models.catalog import (
    AIEmployeeType,
    CommercialModel,
    EmployeeTypeCode,
)
from app.audit.models.audit_event import AuditEvent


async def _register_login_and_select_org(client: AsyncClient, email: str, slug: str) -> dict:
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123!", "fullName": "HR Owner"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SuperSecret123!"}
    )
    token = login.json()["accessToken"]
    org_resp = await client.post(
        "/api/v1/organizations", json={"name": slug, "slug": slug}, headers=_auth(token)
    )
    org_id = org_resp.json()["id"]
    csrf = client.cookies.get("aivra_csrf")
    select_resp = await client.post(
        "/api/v1/auth/select-organization",
        json={"organizationId": org_id},
        headers={**_auth(token), "X-CSRF-Token": csrf},
    )
    return {
        "token": select_resp.json()["accessToken"],
        "org_id": org_id,
        "user_id": register_resp.json()["id"],
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _activate_hr(db_session: AsyncSession, organization_id: str) -> None:
    existing = await db_session.execute(
        select(AIEmployeeType).where(AIEmployeeType.code == EmployeeTypeCode.HR)
    )
    hr_type = existing.scalars().first()
    if hr_type is None:
        hr_type = AIEmployeeType(
            code=EmployeeTypeCode.HR,
            name="AI HR Employee",
            description="Recruiting automation",
            commercial_model=CommercialModel.SELF_SERVICE_SUBSCRIPTION,
        )
        db_session.add(hr_type)
        await db_session.flush()
    db_session.add(
        EmployeeProvision(
            organization_id=organization_id,
            employee_type_id=hr_type.id,
            status=ProvisionStatus.ACTIVE,
        )
    )
    await db_session.flush()


async def _seed_identity(
    db_session: AsyncSession,
    organization_id: str,
    *,
    full_name: str = "Jane Doe",
    email: str = "jane@example.com",
) -> CandidateIdentity:
    identity = CandidateIdentity(
        organization_id=organization_id, full_name=full_name, email=email
    )
    db_session.add(identity)
    await db_session.flush()
    return identity


async def _seed_hr_review_candidate(
    db_session: AsyncSession, organization_id: str, interviewer_user_id: str
) -> tuple[HrJob, Candidate]:
    job = HrJob(
        organization_id=organization_id,
        created_by_user_id=interviewer_user_id,
        title="Backend Engineer",
        requirements=["Python"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()

    identity = await _seed_identity(db_session, organization_id)

    candidate = Candidate(
        organization_id=organization_id,
        job_id=job.id,
        identity_id=identity.id,
        source=CandidateSource.RESUME_UPLOAD,
        stage=CandidateStage.HR_REVIEW,
    )
    db_session.add(candidate)
    await db_session.flush()
    return job, candidate


async def test_hr_routes_require_active_entitlement(client: AsyncClient) -> None:
    session = await _register_login_and_select_org(client, "no-hr@example.com", "no-hr-org")
    response = await client.get("/api/v1/hr/jobs", headers=_auth(session["token"]))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EMPLOYEE_ACCESS_DENIED"


async def test_job_creation_and_listing(client: AsyncClient, db_session: AsyncSession) -> None:
    session = await _register_login_and_select_org(client, "jobs-owner@example.com", "jobs-org")
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    create_resp = await client.post(
        "/api/v1/hr/jobs",
        json={"title": "Backend Engineer", "requirements": ["Python", "PostgreSQL"]},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    assert create_resp.json()["status"] == "open"

    list_resp = await client.get("/api/v1/hr/jobs", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


async def test_candidate_approval_screening_and_scheduling_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(client, "pipeline-owner@example.com", "pipe-org")
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    _job, candidate = await _seed_hr_review_candidate(
        db_session, session["org_id"], session["user_id"]
    )

    # HR_REVIEW gate: approve for screening.
    approve_screening_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/approve-for-screening",
        json={"note": "Strong resume match"},
        headers=headers,
    )
    assert approve_screening_resp.status_code == 200
    assert approve_screening_resp.json()["stage"] == "screening_approved"

    # Every approval action must produce an audit event (spec section 38).
    audit_result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.resource_id == candidate.id)
    )
    audit_rows = audit_result.scalars().all()
    assert any(e.action == "CANDIDATE_APPROVED_FOR_SCREENING" for e in audit_rows)

    # Screening call lifecycle.
    start_resp = await client.post(
        f"/api/v1/hr/screenings/candidates/{candidate.id}/start", headers=headers
    )
    assert start_resp.status_code == 201
    assert start_resp.json()["status"] == "in_progress"

    complete_resp = await client.post(
        f"/api/v1/hr/screenings/candidates/{candidate.id}/complete",
        json={"resultSummary": "Strong communication, matches role requirements."},
        headers=headers,
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"

    # Human review gate would normally move HUMAN_REVIEW -> INTERVIEW_PENDING;
    # simulate reviewer sign-off directly since that's a manual HR action with
    # no dedicated endpoint beyond approve-for-interview itself.
    candidate_row = await db_session.get(Candidate, candidate.id)
    assert candidate_row is not None
    candidate_row.stage = CandidateStage.HUMAN_REVIEW

    approve_interview_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/approve-for-interview",
        json={},
        headers=headers,
    )
    assert approve_interview_resp.status_code == 200
    assert approve_interview_resp.json()["stage"] == "interview_pending"

    interview_resp = await client.get(
        f"/api/v1/hr/candidates/{candidate.id}/interview", headers=headers
    )
    assert interview_resp.status_code == 200
    interview_id = interview_resp.json()["id"]
    assert interview_resp.json()["status"] == "pending_approval"

    approve_resp = await client.post(
        f"/api/v1/hr/interviews/{interview_id}/approve", headers=headers
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    start_time = datetime.now(UTC) + timedelta(days=1)
    slot_resp = await client.post(
        "/api/v1/hr/scheduling/slots",
        json={
            "interviewerUserId": session["user_id"],
            "startTime": start_time.isoformat(),
            "endTime": (start_time + timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    )
    assert slot_resp.status_code == 201
    slot_id = slot_resp.json()["id"]

    book_resp = await client.post(
        "/api/v1/hr/scheduling/book",
        json={"slotId": slot_id, "candidateId": candidate.id},
        headers=headers,
    )
    assert book_resp.status_code == 200, book_resp.text
    assert book_resp.json()["status"] == "scheduled"
    # No calendar integration connected in this test — meeting link is
    # legitimately absent rather than faked (see SchedulingService docstring).
    assert book_resp.json()["meetingLink"] is None

    candidate_after_booking = await db_session.get(Candidate, candidate.id)
    assert candidate_after_booking is not None
    assert candidate_after_booking.stage == CandidateStage.INTERVIEW_SCHEDULED

    complete_interview_resp = await client.post(
        f"/api/v1/hr/interviews/{interview_id}/complete",
        json={"notes": "Great culture fit, recommend hire."},
        headers=headers,
    )
    assert complete_interview_resp.status_code == 200
    assert complete_interview_resp.json()["status"] == "completed"

    final_candidate = await db_session.get(Candidate, candidate.id)
    assert final_candidate is not None
    assert final_candidate.stage == CandidateStage.COMPLETED


async def test_candidate_identity_correction_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "correction-owner@example.com", "correction-org"
    )
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    _job, candidate = await _seed_hr_review_candidate(
        db_session, session["org_id"], session["user_id"]
    )

    patch_resp = await client.patch(
        f"/api/v1/hr/candidates/{candidate.id}",
        json={"fullName": "Jane A. Doe", "email": "jane.doe@example.com"},
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["fullName"] == "Jane A. Doe"
    assert patch_resp.json()["email"] == "jane.doe@example.com"

    audit_result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.resource_id == candidate.id)
    )
    audit_rows = audit_result.scalars().all()
    assert any(e.action == "CANDIDATE_IDENTITY_CORRECTED" for e in audit_rows)

    # A no-op patch (nothing actually changed) must not add a second audit event.
    noop_resp = await client.patch(
        f"/api/v1/hr/candidates/{candidate.id}",
        json={"fullName": "Jane A. Doe"},
        headers=headers,
    )
    assert noop_resp.status_code == 200
    audit_result_after = await db_session.execute(
        select(AuditEvent).where(AuditEvent.resource_id == candidate.id)
    )
    assert len(audit_result_after.scalars().all()) == len(audit_rows)


async def test_hr_data_is_isolated_per_tenant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session_a = await _register_login_and_select_org(client, "tenant-a@example.com", "hr-tenant-a")
    await _activate_hr(db_session, session_a["org_id"])
    session_b = await _register_login_and_select_org(client, "tenant-b@example.com", "hr-tenant-b")
    await _activate_hr(db_session, session_b["org_id"])

    create_resp = await client.post(
        "/api/v1/hr/jobs",
        json={"title": "Tenant A Only Job", "requirements": []},
        headers=_auth(session_a["token"]),
    )
    job_id = create_resp.json()["id"]

    # Tenant B must not be able to fetch tenant A's job by ID.
    get_resp = await client.get(f"/api/v1/hr/jobs/{job_id}", headers=_auth(session_b["token"]))
    assert get_resp.status_code == 404

    # And tenant B's job listing must never include tenant A's job.
    list_resp = await client.get("/api/v1/hr/jobs", headers=_auth(session_b["token"]))
    assert all(job["id"] != job_id for job in list_resp.json())
