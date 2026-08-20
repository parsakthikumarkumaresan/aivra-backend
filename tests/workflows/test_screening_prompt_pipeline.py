"""Direct tests of the AI screening prompt generation pipeline (spec
sections 2-4): the prompt is never blank, follows the fixed structure, is
grounded in the actual job/candidate/JD-match data supplied, and fails
loudly (never falls back to a generic/fake prompt) when the model returns
an incomplete result.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.models.assessment import Assessment, AssessmentKind
from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage
from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.models.resume import Resume, ResumeProcessingStatus
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.workflows import screening_prompt_pipeline
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.shared.security.passwords import hash_password
from tests.fakes.fake_ai_providers import FakeLLMProvider

_RESUME_PROFILE = {
    "fullName": "Jane Doe",
    "email": "jane@example.com",
    "phone": "555-0100",
    "skills": ["Python", "LangGraph", "LiveKit"],
    "totalExperienceYears": 5.0,
    "workHistory": [
        {"company": "Acme", "title": "Senior Engineer", "durationMonths": 36},
    ],
    "education": [{"institution": "State University", "degree": "BSc Computer Science"}],
}

_SECTIONS_RESPONSE = {
    "screeningObjective": "Assess fit for the Backend Engineer role.",
    "opening": "Hi Jane, this is the AIVRA screening assistant calling from Acme Corp.",
    "candidateBackground": "Tell me about your current role at Acme.",
    "jdQuestions": [
        {
            "requirement": "Experience with multi-agent voice systems",
            "question": "Could you describe the multi-agent voice systems you've built?",
        }
    ],
    "candidateQuestions": ["You listed LiveKit — what did you build with it at Acme?"],
    "compensation": "What is your current CTC, and what are you expecting?",
    "availability": "Are you currently serving notice, and if so, what's the period?",
    "closing": "Thanks for your time — our HR team will follow up on next steps.",
}


async def _seed(db_session: AsyncSession, *, slug: str = "voice-screen-test") -> tuple[
    Organization, HrJob, Candidate
]:
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
        company_name="Acme Corp",
        description=(
            "Looking for experience with multi-agent systems and agentic voice development."
        ),
        requirements=["Experience with multi-agent voice systems", "5+ years Python"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()

    identity = CandidateIdentity(
        organization_id=org.id, full_name="Jane Doe", email="jane@example.com", phone="555-0100"
    )
    db_session.add(identity)
    await db_session.flush()

    candidate = Candidate(
        organization_id=org.id,
        job_id=job.id,
        identity_id=identity.id,
        stage=CandidateStage.SCREENING_APPROVED,
    )
    db_session.add(candidate)
    await db_session.flush()

    resume = Resume(
        organization_id=org.id,
        job_id=job.id,
        candidate_id=candidate.id,
        storage_key="resumes/jane.pdf",
        original_filename="jane.pdf",
        content_type="application/pdf",
        size_bytes=100,
        checksum_sha256="a" * 64,
        status=ResumeProcessingStatus.COMPLETED,
        extracted_profile=_RESUME_PROFILE,
    )
    db_session.add(resume)
    await db_session.flush()
    candidate.resume_id = resume.id
    await db_session.flush()

    db_session.add(
        Assessment(
            organization_id=org.id,
            candidate_id=candidate.id,
            kind=AssessmentKind.JD_MATCH,
            overall_score=88.0,
            skill_match=90.0,
            experience_match=85.0,
            missing_requirements=["Kubernetes"],
            evidence=[
                {
                    "requirement": "Experience with multi-agent voice systems",
                    "matched": True,
                    "evidenceText": "Built multi-agent voice systems with LiveKit at Acme.",
                }
            ],
            model_version="gpt-4o-mini",
            prompt_version="v1",
            rubric_version="v1",
        )
    )
    await db_session.flush()

    return org, job, candidate


async def _seed_screening(
    db_session: AsyncSession, org: Organization, candidate: Candidate
) -> Screening:
    screening = await ScreeningRepository(db_session).add(
        Screening(
            organization_id=org.id, candidate_id=candidate.id, status=ScreeningStatus.PENDING
        )
    )
    await db_session.flush()
    return screening


async def test_generate_screening_prompt_happy_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, _job, candidate = await _seed(db_session)
    screening = await _seed_screening(db_session, org, candidate)

    llm = FakeLLMProvider({"screening_prompt_sections": _SECTIONS_RESPONSE})
    monkeypatch.setattr(screening_prompt_pipeline, "get_hr_llm_provider", lambda: llm)

    updated = await screening_prompt_pipeline.generate_screening_prompt(
        db_session, organization_id=org.id, screening_id=screening.id
    )

    assert updated.prompt_text is not None
    assert updated.prompt_text.strip() != ""
    assert updated.prompt_generated_at is not None

    # Fixed structure, in order (spec section 3).
    text = updated.prompt_text
    headers = [
        "## Candidate",
        "## Screening Objective",
        "## Opening",
        "## Candidate Background",
        "## JD-Specific Questions",
        "## Candidate-Specific Questions",
        "## Compensation",
        "## Availability",
        "## Closing",
    ]
    positions = [text.index(h) for h in headers]
    assert positions == sorted(positions)

    # Grounded in the actual JD requirement and candidate evidence supplied.
    assert "multi-agent voice systems" in text
    assert "LiveKit" in text
    assert "Jane Doe" in text
    assert "Acme Corp" in text

    assert updated.prompt_history is not None
    assert len(updated.prompt_history) == 1
    assert updated.prompt_history[0]["source"] == "generated"


@pytest.mark.parametrize(
    "bad_field,bad_value",
    [
        ("opening", ""),
        ("compensation", "   "),
    ],
)
async def test_generate_screening_prompt_fails_loudly_on_blank_section(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, bad_field: str, bad_value: str
) -> None:
    org, _job, candidate = await _seed(db_session, slug=f"blank-{bad_field}")
    screening = await _seed_screening(db_session, org, candidate)

    broken_response = {**_SECTIONS_RESPONSE, bad_field: bad_value}
    llm = FakeLLMProvider({"screening_prompt_sections": broken_response})
    monkeypatch.setattr(screening_prompt_pipeline, "get_hr_llm_provider", lambda: llm)

    with pytest.raises(screening_prompt_pipeline.ScreeningPromptGenerationError):
        await screening_prompt_pipeline.generate_screening_prompt(
            db_session, organization_id=org.id, screening_id=screening.id
        )

    # No fallback/generic prompt is ever persisted on failure.
    screening_row = await ScreeningRepository(db_session).get_by_id(org.id, screening.id)
    assert screening_row is not None
    assert screening_row.prompt_text is None


async def test_generate_screening_prompt_fails_loudly_with_no_jd_questions(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, _job, candidate = await _seed(db_session, slug="no-jd-questions")
    screening = await _seed_screening(db_session, org, candidate)

    broken_response = {**_SECTIONS_RESPONSE, "jdQuestions": []}
    llm = FakeLLMProvider({"screening_prompt_sections": broken_response})
    monkeypatch.setattr(screening_prompt_pipeline, "get_hr_llm_provider", lambda: llm)

    with pytest.raises(screening_prompt_pipeline.ScreeningPromptGenerationError):
        await screening_prompt_pipeline.generate_screening_prompt(
            db_session, organization_id=org.id, screening_id=screening.id
        )


async def test_generate_screening_prompt_fails_loudly_on_llm_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, _job, candidate = await _seed(db_session, slug="llm-error")
    screening = await _seed_screening(db_session, org, candidate)

    llm = FakeLLMProvider({"screening_prompt_sections": RuntimeError("OpenAI unavailable")})
    monkeypatch.setattr(screening_prompt_pipeline, "get_hr_llm_provider", lambda: llm)

    with pytest.raises(screening_prompt_pipeline.ScreeningPromptGenerationError):
        await screening_prompt_pipeline.generate_screening_prompt(
            db_session, organization_id=org.id, screening_id=screening.id
        )
