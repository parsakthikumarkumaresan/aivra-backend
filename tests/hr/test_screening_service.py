"""Service-level tests for ScreeningService (spec sections 1, 4, 7):
idempotent Start Screening, phone/prompt eligibility gates, prompt edits
scoped to one candidate's screening, and audit events on start/edit.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage
from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.services.screening_service import ScreeningService
from app.ai_employees.hr.workflows import screening_result_pipeline
from app.audit.models.audit_event import AuditEvent
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.shared.errors.exceptions import ConflictError
from app.shared.security.passwords import hash_password
from tests.fakes.fake_ai_providers import FakeLLMProvider


def _service(db_session: AsyncSession) -> ScreeningService:
    return ScreeningService(
        ScreeningRepository(db_session),
        CandidateRepository(db_session),
        CandidateIdentityRepository(db_session),
        AuditService(AuditRepository(db_session)),
    )


async def _seed_candidate(
    db_session: AsyncSession,
    *,
    slug: str,
    phone: str | None = "555-0100",
    stage: CandidateStage = CandidateStage.SCREENING_APPROVED,
) -> tuple[Organization, Candidate]:
    org = Organization(name="Acme", slug=slug)
    db_session.add(org)
    await db_session.flush()

    user = User(
        email=f"hr-{slug}@example.com",
        password_hash=hash_password("SuperSecret123!"),
        full_name="HR Admin",
    )
    db_session.add(user)
    await db_session.flush()

    job = HrJob(
        organization_id=org.id,
        created_by_user_id=user.id,
        title="Backend Engineer",
        requirements=["Python"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()

    identity = CandidateIdentity(
        organization_id=org.id, full_name="Jane Doe", email=f"jane-{slug}@example.com", phone=phone
    )
    db_session.add(identity)
    await db_session.flush()

    candidate = Candidate(
        organization_id=org.id, job_id=job.id, identity_id=identity.id, stage=stage
    )
    db_session.add(candidate)
    await db_session.flush()
    return org, candidate


async def test_start_screening_requires_a_generated_prompt(db_session: AsyncSession) -> None:
    org, candidate = await _seed_candidate(db_session, slug="no-prompt")
    service = _service(db_session)

    try:
        await service.start_screening(org.id, candidate.id, actor_id="user_test")
        raise AssertionError("expected ConflictError")
    except ConflictError as exc:
        assert "prompt" in exc.message.lower()


async def test_start_screening_requires_a_phone_number(db_session: AsyncSession) -> None:
    org, candidate = await _seed_candidate(db_session, slug="no-phone", phone=None)
    service = _service(db_session)
    await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id,
            candidate_id=candidate.id,
            status=ScreeningStatus.PENDING,
            prompt_text="## Candidate\n...",
        )
    )
    await db_session.flush()

    try:
        await service.start_screening(org.id, candidate.id, actor_id="user_test")
        raise AssertionError("expected ConflictError")
    except ConflictError as exc:
        assert "phone" in exc.message.lower()


async def test_start_screening_is_idempotent(db_session: AsyncSession) -> None:
    org, candidate = await _seed_candidate(db_session, slug="idempotent")
    service = _service(db_session)
    await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id,
            candidate_id=candidate.id,
            status=ScreeningStatus.PENDING,
            prompt_text="## Candidate\n...",
        )
    )
    await db_session.flush()

    screening = await service.start_screening(org.id, candidate.id, actor_id="user_test")
    assert screening.status == ScreeningStatus.IN_PROGRESS

    try:
        await service.start_screening(org.id, candidate.id, actor_id="user_test")
        raise AssertionError("expected ConflictError on duplicate start")
    except ConflictError:
        pass

    # Exactly one screening row for the candidate — no duplicate created.
    all_screenings = await ScreeningRepository(db_session).list_all(org.id)
    assert len([s for s in all_screenings if s.candidate_id == candidate.id]) == 1

    audit_result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.resource_id == screening.id, AuditEvent.action == "SCREENING_CALL_STARTED"
        )
    )
    assert len(audit_result.scalars().all()) == 1


async def test_start_screening_allows_retry_after_failure(db_session: AsyncSession) -> None:
    org, candidate = await _seed_candidate(db_session, slug="retry")
    service = _service(db_session)
    screening = await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id,
            candidate_id=candidate.id,
            status=ScreeningStatus.PENDING,
            prompt_text="## Candidate\n...",
        )
    )
    await db_session.flush()

    await service.start_screening(org.id, candidate.id, actor_id="user_test")
    await service.mark_dispatch_failed(org.id, screening.id, reason="SIP trunk rejected the call")

    retried = await service.start_screening(org.id, candidate.id, actor_id="user_test")
    assert retried.status == ScreeningStatus.IN_PROGRESS
    assert retried.failure_reason is None


async def test_update_prompt_does_not_leak_across_candidates(db_session: AsyncSession) -> None:
    org, candidate_a = await _seed_candidate(db_session, slug="edit-a")
    _org_b, candidate_b = await _seed_candidate(db_session, slug="edit-b")

    service = _service(db_session)
    screening_a = await service.ensure_screening(org.id, candidate_a.id)
    screening_a.prompt_text = "## Candidate\noriginal a"

    updated_a = await service.update_prompt(
        org.id, candidate_a.id, prompt_text="## Candidate\nedited a", actor_id="user_a"
    )
    assert updated_a.prompt_text == "## Candidate\nedited a"
    assert updated_a.prompt_edited_by_user_id == "user_a"
    assert updated_a.prompt_history is not None
    assert updated_a.prompt_history[-1]["source"] == "hr_edit"

    # Candidate B's screening (separate org/candidate) is untouched.
    screening_b = await ScreeningRepository(db_session).get_for_candidate(
        candidate_b.organization_id, candidate_b.id
    )
    assert screening_b is None  # never created — editing A must not create/touch B's row

    audit_result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.resource_id == screening_a.id, AuditEvent.action == "SCREENING_PROMPT_EDITED"
        )
    )
    assert len(audit_result.scalars().all()) == 1


async def test_generate_result_recovery_path_advances_candidate_stage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, candidate = await _seed_candidate(
        db_session, slug="generate-result", stage=CandidateStage.SCREENING
    )
    screening = await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id,
            candidate_id=candidate.id,
            status=ScreeningStatus.IN_PROGRESS,
            transcript=[{"speaker": "candidate", "text": "Sounds good.", "isFinal": True}],
        )
    )
    await db_session.flush()

    llm = FakeLLMProvider(
        {
            "screening_result": {
                "recommendation": "proceed",
                "recommendationRationale": "Positive signal in the brief transcript.",
                "currentCtc": None,
                "expectedCtc": None,
                "noticePeriod": None,
                "immediateAvailability": None,
                "joiningDate": None,
                "candidateQuestions": [],
                "gaps": [],
                "jdEvidence": [],
            }
        }
    )
    monkeypatch.setattr(screening_result_pipeline, "get_hr_llm_provider", lambda: llm)

    service = _service(db_session)
    updated = await service.generate_result(org.id, candidate.id)

    assert updated.id == screening.id
    assert updated.status == ScreeningStatus.COMPLETED
    candidate_row = await CandidateRepository(db_session).get_by_id(org.id, candidate.id)
    assert candidate_row is not None
    # Advances straight through the fleeting SCREENED state to HUMAN_REVIEW —
    # there is no separate manual "submit for review" action, so a completed
    # screening must land somewhere the Gate 2 approval UI can act on it.
    assert candidate_row.stage == CandidateStage.HUMAN_REVIEW
