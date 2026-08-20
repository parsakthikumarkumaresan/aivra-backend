"""Direct tests of the screening result generation pipeline (spec section
14): the result is derived only from the actual transcript/JD, is advisory
only, and a call with no captured transcript fails loudly rather than being
marked completed.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage
from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.workflows import screening_result_pipeline
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.shared.security.passwords import hash_password
from tests.fakes.fake_ai_providers import FakeLLMProvider

_TRANSCRIPT = [
    {
        "speaker": "assistant",
        "text": "Hi Jane, could you tell me about your LiveKit work?",
        "isFinal": True,
    },
    {
        "speaker": "candidate",
        "text": "I built a multi-agent voice screener using LiveKit.",
        "isFinal": True,
    },
    {"speaker": "assistant", "text": "What's your current and expected CTC?", "isFinal": True},
    {"speaker": "candidate", "text": "Current is 20 LPA, expecting 28 LPA.", "isFinal": True},
]

_RESULT_RESPONSE = {
    "recommendation": "proceed",
    "recommendationRationale": "Strong hands-on LiveKit multi-agent experience matching the JD.",
    "currentCtc": "20 LPA",
    "expectedCtc": "28 LPA",
    "noticePeriod": None,
    "immediateAvailability": None,
    "joiningDate": None,
    "candidateQuestions": [],
    "gaps": [],
    "jdEvidence": [
        {
            "requirement": "Experience with multi-agent voice systems",
            "evidence": "Built a multi-agent voice screener using LiveKit.",
            "transcriptRef": None,
        }
    ],
}


async def _seed(db_session: AsyncSession, *, slug: str) -> tuple[Organization, Candidate]:
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
        requirements=["Experience with multi-agent voice systems"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()

    identity = CandidateIdentity(
        organization_id=org.id,
        full_name="Jane Doe",
        email=f"jane-{slug}@example.com",
        phone="555-0100",
    )
    db_session.add(identity)
    await db_session.flush()

    candidate = Candidate(
        organization_id=org.id,
        job_id=job.id,
        identity_id=identity.id,
        stage=CandidateStage.SCREENING,
    )
    db_session.add(candidate)
    await db_session.flush()
    return org, candidate


async def test_generate_screening_result_happy_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, candidate = await _seed(db_session, slug="result-happy")
    screening = await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id,
            candidate_id=candidate.id,
            status=ScreeningStatus.IN_PROGRESS,
            transcript=_TRANSCRIPT,
        )
    )
    await db_session.flush()

    llm = FakeLLMProvider({"screening_result": _RESULT_RESPONSE})
    monkeypatch.setattr(screening_result_pipeline, "get_hr_llm_provider", lambda: llm)

    updated = await screening_result_pipeline.generate_screening_result(
        db_session, organization_id=org.id, screening_id=screening.id
    )

    assert updated.status == ScreeningStatus.COMPLETED
    assert updated.completed_at is not None
    assert updated.result is not None
    assert updated.result["recommendation"] == "proceed"
    assert updated.result["currentCtc"] == "20 LPA"
    assert updated.result["expectedCtc"] == "28 LPA"
    assert updated.result_summary == _RESULT_RESPONSE["recommendationRationale"]


async def test_generate_screening_result_fails_loudly_with_no_transcript(
    db_session: AsyncSession,
) -> None:
    org, candidate = await _seed(db_session, slug="result-no-transcript")
    screening = await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id, candidate_id=candidate.id, status=ScreeningStatus.IN_PROGRESS
        )
    )
    await db_session.flush()

    updated = await screening_result_pipeline.generate_screening_result(
        db_session, organization_id=org.id, screening_id=screening.id
    )

    assert updated.status == ScreeningStatus.FAILED
    assert updated.failure_reason is not None
    assert "transcript" in updated.failure_reason.lower()
    assert updated.result is None


async def test_generate_screening_result_fails_loudly_on_llm_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, candidate = await _seed(db_session, slug="result-llm-error")
    screening = await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id,
            candidate_id=candidate.id,
            status=ScreeningStatus.IN_PROGRESS,
            transcript=_TRANSCRIPT,
        )
    )
    await db_session.flush()

    llm = FakeLLMProvider({"screening_result": RuntimeError("OpenAI unavailable")})
    monkeypatch.setattr(screening_result_pipeline, "get_hr_llm_provider", lambda: llm)

    updated = await screening_result_pipeline.generate_screening_result(
        db_session, organization_id=org.id, screening_id=screening.id
    )

    assert updated.status == ScreeningStatus.FAILED
    assert updated.failure_reason is not None
    assert updated.result is None
