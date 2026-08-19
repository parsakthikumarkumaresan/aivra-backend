"""Candidate reconsideration, archival/restore, and the candidate-identity
vs. per-job-application split (spec: "AIVRA is a multi-tenant recruitment
SaaS product" — a rejection for one job must not affect any other job's
application for the same person).

Resume upload/extraction/matching is covered in tests/workflows/
test_resume_pipeline.py; job creation/candidate approval gates/scheduling
in tests/api/test_hr_flow.py — this file focuses on the lifecycle actions
added on top: reconsider, archive, bulk archive, restore, and multi-job
independence.
"""

from __future__ import annotations

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
from app.identity.models.user import User
from app.organizations.models.membership import OrganizationMember
from app.shared.rbac.roles import OrgRole
from app.shared.security.passwords import hash_password
from app.shared.security.tokens import create_access_token


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


async def _seed_job(
    db_session: AsyncSession, organization_id: str, user_id: str, *, title: str = "Backend Engineer"
) -> HrJob:
    job = HrJob(
        organization_id=organization_id,
        created_by_user_id=user_id,
        title=title,
        requirements=["Python"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def _seed_identity(
    db_session: AsyncSession,
    organization_id: str,
    *,
    full_name: str = "Jane Doe",
    email: str = "jane@example.com",
) -> CandidateIdentity:
    identity = CandidateIdentity(organization_id=organization_id, full_name=full_name, email=email)
    db_session.add(identity)
    await db_session.flush()
    return identity


async def _seed_candidate(
    db_session: AsyncSession,
    organization_id: str,
    job_id: str,
    identity_id: str,
    *,
    stage: CandidateStage = CandidateStage.HR_REVIEW,
    rejected_reason: str | None = None,
) -> Candidate:
    candidate = Candidate(
        organization_id=organization_id,
        job_id=job_id,
        identity_id=identity_id,
        source=CandidateSource.RESUME_UPLOAD,
        stage=stage,
        rejected_reason=rejected_reason,
    )
    db_session.add(candidate)
    await db_session.flush()
    return candidate


async def _viewer_token(db_session: AsyncSession, organization_id: str) -> str:
    """A user who belongs to the org (and can therefore see HR data) but
    holds a role outside HR_OPERATOR_ROLES — used to prove mutating
    endpoints reject a real, legitimately-authenticated-but-unauthorized user.
    """
    user = User(
        email=f"viewer-{organization_id}@example.com",
        full_name="Read Only Viewer",
        password_hash=hash_password("SuperSecret123!"),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=organization_id, user_id=user.id, role=OrgRole.VIEWER)
    )
    await db_session.flush()
    return create_access_token(
        user_id=user.id,
        organization_id=organization_id,
        role=OrgRole.VIEWER.value,
        session_id="ses_viewer_test",
    )


async def test_reconsider_moves_rejected_to_hr_review_and_preserves_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "reconsider-owner@example.com", "reconsider-org"
    )
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    job = await _seed_job(db_session, session["org_id"], session["user_id"])
    identity = await _seed_identity(db_session, session["org_id"])
    candidate = await _seed_candidate(
        db_session, session["org_id"], job.id, identity.id, stage=CandidateStage.HR_REVIEW
    )

    reject_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/reject",
        json={"note": "Not enough experience"},
        headers=headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["stage"] == "rejected"
    assert reject_resp.json()["rejectedReason"] == "Not enough experience"

    reconsider_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/reconsider",
        json={"note": "Hiring manager asked for a second look"},
        headers=headers,
    )
    assert reconsider_resp.status_code == 200, reconsider_resp.text
    assert reconsider_resp.json()["stage"] == "hr_review"
    # Current-state reason field no longer describes a rejected application.
    assert reconsider_resp.json()["rejectedReason"] is None

    # Both the original rejection and the reconsideration remain in the
    # audit trail — the historical rejection is never erased.
    audit_rows = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.resource_id == candidate.id)))
        .scalars()
        .all()
    )
    actions = [e.action for e in audit_rows]
    assert "CANDIDATE_REJECTED" in actions
    assert "CANDIDATE_RECONSIDERED" in actions


async def test_reconsider_rejects_candidate_not_currently_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "reconsider-invalid@example.com", "reconsider-invalid-org"
    )
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    job = await _seed_job(db_session, session["org_id"], session["user_id"])
    identity = await _seed_identity(db_session, session["org_id"])
    candidate = await _seed_candidate(
        db_session, session["org_id"], job.id, identity.id, stage=CandidateStage.HR_REVIEW
    )

    resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/reconsider", json={}, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_reconsider_denied_for_unauthorized_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "reconsider-rbac@example.com", "reconsider-rbac-org"
    )
    await _activate_hr(db_session, session["org_id"])

    job = await _seed_job(db_session, session["org_id"], session["user_id"])
    identity = await _seed_identity(db_session, session["org_id"])
    candidate = await _seed_candidate(
        db_session, session["org_id"], job.id, identity.id, stage=CandidateStage.REJECTED
    )

    viewer_token = await _viewer_token(db_session, session["org_id"])
    resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/reconsider", json={}, headers=_auth(viewer_token)
    )
    assert resp.status_code == 403


async def test_reconsider_is_isolated_per_tenant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session_a = await _register_login_and_select_org(
        client, "reconsider-tenant-a@example.com", "reconsider-tenant-a"
    )
    await _activate_hr(db_session, session_a["org_id"])
    session_b = await _register_login_and_select_org(
        client, "reconsider-tenant-b@example.com", "reconsider-tenant-b"
    )
    await _activate_hr(db_session, session_b["org_id"])

    job = await _seed_job(db_session, session_a["org_id"], session_a["user_id"])
    identity = await _seed_identity(db_session, session_a["org_id"])
    candidate = await _seed_candidate(
        db_session, session_a["org_id"], job.id, identity.id, stage=CandidateStage.REJECTED
    )

    resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/reconsider",
        json={},
        headers=_auth(session_b["token"]),
    )
    assert resp.status_code == 404


async def test_archive_individual_candidate_and_audits(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "archive-owner@example.com", "archive-org"
    )
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    job = await _seed_job(db_session, session["org_id"], session["user_id"])
    identity = await _seed_identity(db_session, session["org_id"])
    candidate = await _seed_candidate(db_session, session["org_id"], job.id, identity.id)

    archive_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/archive", headers=headers
    )
    assert archive_resp.status_code == 200, archive_resp.text
    assert archive_resp.json()["archivedAt"] is not None
    assert archive_resp.json()["archivedByUserId"] == session["user_id"]
    # Archiving is lifecycle-only — stage/decision history is untouched.
    assert archive_resp.json()["stage"] == "hr_review"

    audit_rows = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.resource_id == candidate.id)))
        .scalars()
        .all()
    )
    assert any(e.action == "CANDIDATE_ARCHIVED" for e in audit_rows)

    # Disappears from the default (active) list...
    active_list = await client.get("/api/v1/hr/candidates", headers=headers)
    assert candidate.id not in [c["id"] for c in active_list.json()]
    # ...but is still visible in the archived view.
    archived_list = await client.get("/api/v1/hr/candidates?status=archived", headers=headers)
    assert candidate.id in [c["id"] for c in archived_list.json()]

    # Archiving an already-archived candidate is rejected, not silently re-applied.
    second_archive_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/archive", headers=headers
    )
    assert second_archive_resp.status_code == 409


async def test_archive_denied_for_unauthorized_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "archive-rbac@example.com", "archive-rbac-org"
    )
    await _activate_hr(db_session, session["org_id"])

    job = await _seed_job(db_session, session["org_id"], session["user_id"])
    identity = await _seed_identity(db_session, session["org_id"])
    candidate = await _seed_candidate(db_session, session["org_id"], job.id, identity.id)

    viewer_token = await _viewer_token(db_session, session["org_id"])
    resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/archive", headers=_auth(viewer_token)
    )
    assert resp.status_code == 403


async def test_bulk_archive_respects_tenant_isolation_and_reports_skipped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session_a = await _register_login_and_select_org(
        client, "bulk-tenant-a@example.com", "bulk-tenant-a"
    )
    await _activate_hr(db_session, session_a["org_id"])
    session_b = await _register_login_and_select_org(
        client, "bulk-tenant-b@example.com", "bulk-tenant-b"
    )
    await _activate_hr(db_session, session_b["org_id"])

    job_a = await _seed_job(db_session, session_a["org_id"], session_a["user_id"])
    identity_a1 = await _seed_identity(db_session, session_a["org_id"], email="cand1@example.com")
    identity_a2 = await _seed_identity(db_session, session_a["org_id"], email="cand2@example.com")
    candidate_a1 = await _seed_candidate(db_session, session_a["org_id"], job_a.id, identity_a1.id)
    candidate_a2 = await _seed_candidate(db_session, session_a["org_id"], job_a.id, identity_a2.id)

    job_b = await _seed_job(db_session, session_b["org_id"], session_b["user_id"])
    identity_b = await _seed_identity(db_session, session_b["org_id"], email="cand3@example.com")
    candidate_b = await _seed_candidate(db_session, session_b["org_id"], job_b.id, identity_b.id)

    # Tenant A bulk-archives its own two candidates plus tenant B's — the
    # cross-tenant id must be skipped, never archived.
    resp = await client.post(
        "/api/v1/hr/candidates/archive",
        json={
            "candidateIds": [
                candidate_a1.id,
                candidate_a2.id,
                candidate_b.id,
                "cand_does_not_exist",
            ]
        },
        headers=_auth(session_a["token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    archived_ids = [c["id"] for c in body["archived"]]
    assert candidate_a1.id in archived_ids
    assert candidate_a2.id in archived_ids
    assert candidate_b.id not in archived_ids
    assert body["skipped"][candidate_b.id] == "not_found"
    assert body["skipped"]["cand_does_not_exist"] == "not_found"

    # Tenant B's candidate was never touched.
    candidate_b_row = await db_session.get(Candidate, candidate_b.id)
    assert candidate_b_row is not None
    assert candidate_b_row.archived_at is None

    audit_rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.resource_id == candidate_a1.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(e.action == "CANDIDATE_ARCHIVED" for e in audit_rows)


async def test_restore_archived_candidate_preserves_history_without_reopening_workflow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session = await _register_login_and_select_org(
        client, "restore-owner@example.com", "restore-org"
    )
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    job = await _seed_job(db_session, session["org_id"], session["user_id"])
    identity = await _seed_identity(db_session, session["org_id"])
    candidate = await _seed_candidate(
        db_session,
        session["org_id"],
        job.id,
        identity.id,
        stage=CandidateStage.REJECTED,
        rejected_reason="Skills mismatch",
    )

    archive_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/archive", headers=headers
    )
    assert archive_resp.status_code == 200

    restore_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/restore", headers=headers
    )
    assert restore_resp.status_code == 200, restore_resp.text
    assert restore_resp.json()["archivedAt"] is None
    assert restore_resp.json()["archivedByUserId"] is None
    # Restore must NOT resurrect the recruitment workflow — still REJECTED,
    # still carrying its rejection reason, exactly as before archiving.
    assert restore_resp.json()["stage"] == "rejected"
    assert restore_resp.json()["rejectedReason"] == "Skills mismatch"

    audit_rows = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.resource_id == candidate.id)))
        .scalars()
        .all()
    )
    actions = [e.action for e in audit_rows]
    assert "CANDIDATE_ARCHIVED" in actions
    assert "CANDIDATE_RESTORED" in actions

    # Restoring a non-archived candidate is rejected.
    second_restore_resp = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/restore", headers=headers
    )
    assert second_restore_resp.status_code == 409

    # Back in the active list.
    active_list = await client.get("/api/v1/hr/candidates", headers=headers)
    assert candidate.id in [c["id"] for c in active_list.json()]


async def test_same_identity_can_have_independent_applications_across_jobs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The core product principle: rejecting a candidate for one job must
    not affect their (independent) application to a different job.
    """
    session = await _register_login_and_select_org(
        client, "multi-job-owner@example.com", "multi-job-org"
    )
    await _activate_hr(db_session, session["org_id"])
    headers = _auth(session["token"])

    job_a = await _seed_job(db_session, session["org_id"], session["user_id"], title="AI Engineer")
    job_b = await _seed_job(
        db_session, session["org_id"], session["user_id"], title="Backend Engineer"
    )
    identity = await _seed_identity(
        db_session, session["org_id"], full_name="Multi Job Candidate", email="multijob@example.com"
    )

    application_a = await _seed_candidate(
        db_session, session["org_id"], job_a.id, identity.id, stage=CandidateStage.HR_REVIEW
    )
    application_b = await _seed_candidate(
        db_session, session["org_id"], job_b.id, identity.id, stage=CandidateStage.HR_REVIEW
    )

    assert application_a.id != application_b.id
    assert application_a.identity_id == application_b.identity_id

    reject_resp = await client.post(
        f"/api/v1/hr/candidates/{application_a.id}/reject",
        json={"note": "Not an AI fit"},
        headers=headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["stage"] == "rejected"

    # Application B — same person, different job — is completely unaffected.
    application_b_resp = await client.get(
        f"/api/v1/hr/candidates/{application_b.id}", headers=headers
    )
    assert application_b_resp.status_code == 200
    assert application_b_resp.json()["stage"] == "hr_review"
    assert application_b_resp.json()["fullName"] == "Multi Job Candidate"

    approve_resp = await client.post(
        f"/api/v1/hr/candidates/{application_b.id}/approve-for-screening", json={}, headers=headers
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["stage"] == "screening_approved"

    # And rejecting/approving B never touched A's already-rejected state.
    application_a_after = await db_session.get(Candidate, application_a.id)
    assert application_a_after is not None
    assert application_a_after.stage == CandidateStage.REJECTED
