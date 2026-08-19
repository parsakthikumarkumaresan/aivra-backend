"""Direct tests of the resume processing pipeline (spec section 9.2) —
covers the full resume-first happy path (Candidate created by the pipeline
after extraction, not before), identity-validation edge cases (missing/
malformed name or email pausing in NEEDS_IDENTITY_REVIEW rather than
inventing data), HR's confirm-identity path, idempotent candidate creation
on duplicate resumes, failures at each AI stage, and resumability after a
retry (the bug this module's design specifically had to avoid, see
app/ai_employees/hr/workflows/resume_pipeline.py docstring).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.models.assessment import AssessmentKind
from app.ai_employees.hr.models.candidate import CandidateStage
from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.models.processing_job import ProcessingJob, ProcessingJobStatus
from app.ai_employees.hr.models.resume import ResumeProcessingStatus
from app.ai_employees.hr.repositories.assessment_repository import AssessmentRepository
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.processing_job_repository import ProcessingJobRepository
from app.ai_employees.hr.repositories.resume_repository import ResumeRepository
from app.ai_employees.hr.services.resume_service import ResumeService
from app.ai_employees.hr.workflows import resume_pipeline
from app.audit.models.audit_event import AuditEvent
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.shared.errors.exceptions import InvalidStateTransitionError, ValidationAppError
from app.shared.security.passwords import hash_password
from tests.fakes.fake_ai_providers import FakeLLMProvider, FakeObjectStorage, FakeOCRProvider

_RESUME_PROFILE = {
    "fullName": "Jane Doe",
    "email": "jane@example.com",
    "phone": "555-0100",
    "skills": ["Python", "PostgreSQL", " Python "],
    "totalExperienceYears": 5.0,
    "workHistory": [{"company": "Acme", "title": "Senior Engineer", "durationMonths": 36}],
    "education": [{"institution": "State University", "degree": "BSc Computer Science"}],
}

_JD_MATCH_RESULT = {
    "overallScore": 88.0,
    "skillMatch": 90.0,
    "experienceMatch": 85.0,
    "missingRequirements": ["Kubernetes"],
    "evidence": [
        {"requirement": "5+ years Python", "matched": True, "evidenceText": "5 years at Acme"}
    ],
}


async def _seed_org_job(
    db_session: AsyncSession,
    *,
    slug: str = "acme-pipeline-test",
    requirements: list[str] | None = None,
    description: str | None = None,
) -> tuple[Organization, HrJob]:
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
        requirements=["5+ years Python", "Kubernetes"] if requirements is None else requirements,
        description=description,
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()
    return org, job


def _resume_service(db_session: AsyncSession, storage) -> ResumeService:
    return ResumeService(
        ResumeRepository(db_session),
        CandidateRepository(db_session),
        JobRepository(db_session),
        ProcessingJobRepository(db_session),
        storage,
        AuditService(AuditRepository(db_session)),
    )


async def _upload_resume(db_session: AsyncSession, org: Organization, job: HrJob):
    storage = FakeObjectStorage()
    service = _resume_service(db_session, storage)
    resume, processing_job = await service.upload_resume(
        organization_id=org.id,
        job_id=job.id,
        filename="resume.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 fake resume bytes",
    )
    return resume, processing_job, storage


async def _latest_processing_job(db_session: AsyncSession, resume_id: str) -> ProcessingJob:
    stmt = (
        select(ProcessingJob)
        .where(ProcessingJob.resume_id == resume_id)
        .order_by(ProcessingJob.id.desc())
    )
    result = await db_session.execute(stmt)
    job_row = result.scalars().first()
    assert job_row is not None
    return job_row


def _patch_providers(
    monkeypatch: pytest.MonkeyPatch, storage, llm_provider, ocr_provider=None
) -> None:
    monkeypatch.setattr(resume_pipeline, "get_hr_llm_provider", lambda: llm_provider)
    monkeypatch.setattr(
        resume_pipeline, "get_ocr_provider", lambda: ocr_provider or FakeOCRProvider()
    )
    monkeypatch.setattr(
        resume_pipeline, "get_object_storage", lambda category: storage  # noqa: ARG005
    )


async def test_resume_pipeline_happy_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(db_session)
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)
    assert resume.candidate_id is None  # no candidate at upload time

    llm = FakeLLMProvider(
        {"resume_profile": _RESUME_PROFILE, "jd_match_result": _JD_MATCH_RESULT}
    )
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.COMPLETED
    assert resume_row.extracted_text
    assert resume_row.extracted_profile["fullName"] == "Jane Doe"
    # Normalizing stage actually ran: skills deduped/lowercased.
    assert resume_row.extracted_profile["normalizedSkills"] == ["postgresql", "python"]
    assert resume_row.candidate_id is not None

    candidate_row = await CandidateRepository(db_session).get_by_id(org.id, resume_row.candidate_id)
    assert candidate_row is not None
    assert candidate_row.full_name == "Jane Doe"
    assert candidate_row.email == "jane@example.com"
    assert candidate_row.resume_id == resume.id
    # MATCHED is a momentary waypoint — matching immediately makes the
    # candidate actionable for HR, so it lands on HR_REVIEW (spec section 9.1).
    assert candidate_row.stage == CandidateStage.HR_REVIEW

    assessment = await AssessmentRepository(db_session).get_latest_for_candidate(
        org.id, candidate_row.id
    )
    assert assessment is not None
    assert assessment.kind == AssessmentKind.JD_MATCH
    assert float(assessment.overall_score) == 88.0
    assert assessment.missing_requirements == ["Kubernetes"]

    assert llm.calls == ["resume_profile", "jd_match_result"]


@pytest.mark.parametrize(
    "profile_overrides",
    [
        pytest.param({"email": ""}, id="missing_email"),
        pytest.param({"fullName": ""}, id="missing_name"),
        pytest.param({"email": "not-an-email"}, id="malformed_email"),
        pytest.param({"fullName": "   "}, id="whitespace_only_name"),
    ],
)
async def test_resume_pipeline_pauses_for_identity_review_on_unusable_identity(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, profile_overrides: dict
) -> None:
    org, job = await _seed_org_job(db_session, slug=f"identity-{uuid.uuid4().hex[:8]}")
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)

    profile = {**_RESUME_PROFILE, **profile_overrides}
    llm = FakeLLMProvider({"resume_profile": profile})
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW
    assert resume_row.candidate_id is None  # never invented — no Candidate created
    assert resume_row.failure_reason  # evidence of why it's paused is retained
    assert resume_row.extracted_profile is not None  # extracted evidence preserved

    # No candidate exists anywhere for this resume.
    all_candidates = await CandidateRepository(db_session).list_filtered(org.id, job_id=job.id)
    assert all_candidates == []

    job_row = await _latest_processing_job(db_session, resume.id)
    assert job_row.status == ProcessingJobStatus.NEEDS_REVIEW


async def test_confirm_identity_creates_candidate_and_resumes_pipeline(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(db_session, slug="confirm-identity")
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)

    llm = FakeLLMProvider({"resume_profile": {**_RESUME_PROFILE, "email": ""}})
    _patch_providers(monkeypatch, storage, llm)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW

    service = _resume_service(db_session, storage)
    candidate, resume_after_confirm, new_processing_job = await service.confirm_identity(
        organization_id=org.id,
        resume_id=resume.id,
        full_name="Jane Doe",
        email="jane@example.com",
        phone=None,
        actor_id="user_test",
    )
    assert candidate.full_name == "Jane Doe"
    assert candidate.email == "jane@example.com"
    assert candidate.stage == CandidateStage.PROCESSING
    assert resume_after_confirm.status == ResumeProcessingStatus.NORMALIZING
    assert resume_after_confirm.candidate_id == candidate.id

    audit_rows = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.resource_id == candidate.id))
    ).scalars().all()
    assert any(e.action == "CANDIDATE_IDENTITY_CONFIRMED" for e in audit_rows)

    # Re-running the pipeline picks up exactly where confirm_identity left it.
    working_llm = FakeLLMProvider({"jd_match_result": _JD_MATCH_RESULT})
    _patch_providers(monkeypatch, storage, working_llm)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_final = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_final is not None
    assert resume_final.status == ResumeProcessingStatus.COMPLETED
    candidate_final = await CandidateRepository(db_session).get_by_id(org.id, candidate.id)
    assert candidate_final is not None
    assert candidate_final.stage == CandidateStage.HR_REVIEW

    latest_job_run = await _latest_processing_job(db_session, resume.id)
    assert latest_job_run.status == ProcessingJobStatus.SUCCEEDED
    assert latest_job_run.id == new_processing_job.id


async def test_confirm_identity_rejects_resume_not_awaiting_review(
    db_session: AsyncSession,
) -> None:
    org, job = await _seed_org_job(db_session, slug="confirm-not-awaiting")
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)
    # resume.status is UPLOADED here, not NEEDS_IDENTITY_REVIEW.
    service = _resume_service(db_session, storage)

    with pytest.raises(InvalidStateTransitionError):
        await service.confirm_identity(
            organization_id=org.id,
            resume_id=resume.id,
            full_name="Jane Doe",
            email="jane@example.com",
            phone=None,
            actor_id="user_test",
        )


async def test_confirm_identity_rejects_invalid_input(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(db_session, slug="confirm-invalid-input")
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)
    llm = FakeLLMProvider({"resume_profile": {**_RESUME_PROFILE, "fullName": ""}})
    _patch_providers(monkeypatch, storage, llm)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    service = _resume_service(db_session, storage)
    with pytest.raises(ValidationAppError):
        await service.confirm_identity(
            organization_id=org.id,
            resume_id=resume.id,
            full_name="   ",
            email="jane@example.com",
            phone=None,
            actor_id="user_test",
        )


async def test_confirm_identity_is_isolated_per_tenant(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_a, job_a = await _seed_org_job(db_session, slug="tenant-a-confirm")
    org_b, _job_b = await _seed_org_job(db_session, slug="tenant-b-confirm")
    resume, _processing_job, storage = await _upload_resume(db_session, org_a, job_a)
    llm = FakeLLMProvider({"resume_profile": {**_RESUME_PROFILE, "email": ""}})
    _patch_providers(monkeypatch, storage, llm)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org_a.id, resume_id=resume.id
    )

    service = _resume_service(db_session, storage)
    from app.shared.errors.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await service.confirm_identity(
            organization_id=org_b.id,
            resume_id=resume.id,
            full_name="Jane Doe",
            email="jane@example.com",
            phone=None,
            actor_id="user_test",
        )


async def test_duplicate_resume_for_same_job_and_email_reuses_candidate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotency + duplicate-resume handling: two resumes uploaded for the
    same job that both extract to the same email must not create two
    Candidate rows — the second upload links to the existing candidate.
    """
    org, job = await _seed_org_job(db_session, slug="duplicate-resume")
    resume1, _pj1, storage1 = await _upload_resume(db_session, org, job)
    llm1 = FakeLLMProvider(
        {"resume_profile": _RESUME_PROFILE, "jd_match_result": _JD_MATCH_RESULT}
    )
    _patch_providers(monkeypatch, storage1, llm1)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume1.id
    )

    resume1_row = await ResumeRepository(db_session).get_by_id(org.id, resume1.id)
    assert resume1_row is not None
    first_candidate_id = resume1_row.candidate_id
    assert first_candidate_id is not None

    resume2, _pj2, storage2 = await _upload_resume(db_session, org, job)
    llm2 = FakeLLMProvider(
        {"resume_profile": _RESUME_PROFILE, "jd_match_result": _JD_MATCH_RESULT}
    )
    _patch_providers(monkeypatch, storage2, llm2)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume2.id
    )

    resume2_row = await ResumeRepository(db_session).get_by_id(org.id, resume2.id)
    assert resume2_row is not None
    assert resume2_row.candidate_id == first_candidate_id  # reused, not duplicated

    all_candidates = await CandidateRepository(db_session).list_filtered(org.id, job_id=job.id)
    assert len(all_candidates) == 1


async def test_resume_pipeline_extraction_failure_sets_failure_state(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(db_session, slug="extraction-failure")
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)

    llm = FakeLLMProvider({"resume_profile": RuntimeError("OpenAI is unreachable")})
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.EXTRACTION_FAILED
    assert "OpenAI is unreachable" in (resume_row.failure_reason or "")
    assert resume_row.candidate_id is None


async def test_resume_pipeline_resumes_from_matching_after_retry(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this design had to avoid: a retry re-entering at MATCHING
    must not depend on EXTRACTING having run in the *same* call — the
    profile has to be reloaded from the persisted Resume row, and the
    candidate created on the first run must not be recreated.
    """
    org, job = await _seed_org_job(db_session, slug="retry-from-matching")
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)

    failing_llm = FakeLLMProvider(
        {
            "resume_profile": _RESUME_PROFILE,
            "jd_match_result": RuntimeError("transient matching error"),
        }
    )
    _patch_providers(monkeypatch, storage, failing_llm)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.MATCHING_FAILED
    candidate_id_after_first_run = resume_row.candidate_id
    assert candidate_id_after_first_run is not None

    # Simulate a retry: reset to the failed stage's re-entry point (what a
    # real retry endpoint/service would do) — MATCHING_FAILED -> MATCHING.
    resume_row.status = ResumeProcessingStatus.MATCHING

    working_llm = FakeLLMProvider({"jd_match_result": _JD_MATCH_RESULT})
    _patch_providers(monkeypatch, storage, working_llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.COMPLETED
    # Candidate identity was not recreated on retry.
    assert resume_row.candidate_id == candidate_id_after_first_run
    # The retry never called resume_profile again — profile was reloaded
    # from resume.extracted_profile, not recomputed.
    assert working_llm.calls == ["jd_match_result"]

    latest_job_run = await _latest_processing_job(db_session, resume.id)
    assert latest_job_run.status == ProcessingJobStatus.SUCCEEDED
    assert latest_job_run.attempts == 2  # one failed run, one successful retry


# ---------------------------------------------------------------------
# JD requirements extraction — regression coverage for a job created with
# only a free-text description and no structured requirements sending an
# empty requirements list into matching, which produced a misleading 0%
# match for every candidate regardless of actual fit.
# ---------------------------------------------------------------------
_AI_ENGINEER_DESCRIPTION = (
    "We are looking for an AI Engineer with 1-5 years of experience to design, "
    "develop, and deploy production-ready AI solutions. Hands-on experience "
    "with Python, Machine Learning, LLMs, RAG, LangChain/LangGraph, REST APIs, "
    "and vector databases is expected."
)

_DERIVED_REQUIREMENTS = {
    "requirements": [
        "Python",
        "Machine Learning",
        "LLMs",
        "RAG",
        "LangChain/LangGraph",
        "REST APIs",
        "Vector databases",
    ]
}

_AI_ENGINEER_PROFILE = {
    "fullName": "Alex Engineer",
    "email": "alex.engineer@example.com",
    "phone": "555-0199",
    "skills": ["Python", "LangChain", "LangGraph", "OpenAI", "RAG", "FastAPI", "pgvector"],
    "totalExperienceYears": 3.0,
    "workHistory": [{"company": "AI Startup", "title": "AI Engineer", "durationMonths": 24}],
    "education": [{"institution": "State University", "degree": "BSc Computer Science"}],
}

_AI_ENGINEER_MATCH_RESULT = {
    "overallScore": 82.0,
    "skillMatch": 90.0,
    "experienceMatch": 70.0,
    "missingRequirements": ["Vector databases"],
    "evidence": [
        {"requirement": "Python", "matched": True, "evidenceText": "Lists Python as a core skill."},
        {
            "requirement": "LLMs",
            "matched": True,
            "evidenceText": "Used OpenAI models in production.",
        },
        {
            "requirement": "LangChain/LangGraph",
            "matched": True,
            "evidenceText": "Lists LangChain and LangGraph directly.",
        },
    ],
}


async def test_matching_derives_requirements_from_description_when_none_provided(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(
        db_session, slug="jd-derive", requirements=[], description=_AI_ENGINEER_DESCRIPTION
    )
    assert job.requirements == []

    resume, _processing_job, storage = await _upload_resume(db_session, org, job)
    llm = FakeLLMProvider(
        {
            "resume_profile": _AI_ENGINEER_PROFILE,
            "job_requirements": _DERIVED_REQUIREMENTS,
            "jd_match_result": _AI_ENGINEER_MATCH_RESULT,
        }
    )
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.COMPLETED

    # Requirements were derived from the description and persisted onto the job.
    job_row = await JobRepository(db_session).get_by_id(org.id, job.id)
    assert job_row is not None
    assert job_row.requirements == _DERIVED_REQUIREMENTS["requirements"]

    assert resume_row.candidate_id is not None
    assessment = await AssessmentRepository(db_session).get_latest_for_candidate(
        org.id, resume_row.candidate_id
    )
    assert assessment is not None
    # The whole point of the fix: a genuinely strong match must not be a fake 0%.
    assert float(assessment.overall_score) == 82.0
    assert float(assessment.skill_match) == 90.0
    assert assessment.missing_requirements == ["Vector databases"]
    assert len(assessment.evidence) == 3

    assert llm.calls == ["resume_profile", "job_requirements", "jd_match_result"]


async def test_matching_reuses_persisted_requirements_for_second_candidate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once requirements are derived for a job, every subsequent candidate
    for that job must be scored against the *same* list — not a freshly
    reworded one per resume (which would make cross-candidate comparison
    meaningless).
    """
    org, job = await _seed_org_job(
        db_session, slug="jd-reuse", requirements=[], description=_AI_ENGINEER_DESCRIPTION
    )

    resume1, _pj1, storage1 = await _upload_resume(db_session, org, job)
    llm1 = FakeLLMProvider(
        {
            "resume_profile": _AI_ENGINEER_PROFILE,
            "job_requirements": _DERIVED_REQUIREMENTS,
            "jd_match_result": _AI_ENGINEER_MATCH_RESULT,
        }
    )
    _patch_providers(monkeypatch, storage1, llm1)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume1.id
    )

    second_profile = {
        **_AI_ENGINEER_PROFILE,
        "fullName": "Jordan Engineer",
        "email": "jordan@example.com",
    }
    resume2, _pj2, storage2 = await _upload_resume(db_session, org, job)
    # Deliberately no "job_requirements" canned response — if the pipeline
    # tried to re-derive requirements for this second candidate, FakeLLMProvider
    # would raise KeyError and this test would fail.
    llm2 = FakeLLMProvider(
        {"resume_profile": second_profile, "jd_match_result": _AI_ENGINEER_MATCH_RESULT}
    )
    _patch_providers(monkeypatch, storage2, llm2)
    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume2.id
    )

    resume2_row = await ResumeRepository(db_session).get_by_id(org.id, resume2.id)
    assert resume2_row is not None
    assert resume2_row.status == ResumeProcessingStatus.COMPLETED
    assert llm2.calls == ["resume_profile", "jd_match_result"]  # no job_requirements call


async def test_matching_fails_when_job_has_no_requirements_or_description(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job with literally nothing to score against must fail loudly, not
    silently report a misleading 0% as if the candidate failed every check.
    """
    org, job = await _seed_org_job(db_session, slug="jd-nothing", requirements=[], description=None)
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)
    llm = FakeLLMProvider({"resume_profile": _AI_ENGINEER_PROFILE})
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.MATCHING_FAILED
    assert "no requirements" in (resume_row.failure_reason or "").lower()
    # Identity was fine — only matching had nothing to score.
    assert resume_row.candidate_id is not None
    assessment = await AssessmentRepository(db_session).get_latest_for_candidate(
        org.id, resume_row.candidate_id
    )
    assert assessment is None  # no fabricated assessment was persisted


async def test_matching_fails_when_requirements_extraction_itself_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(
        db_session, slug="jd-extract-fail", requirements=[], description=_AI_ENGINEER_DESCRIPTION
    )
    resume, _processing_job, storage = await _upload_resume(db_session, org, job)
    llm = FakeLLMProvider(
        {
            "resume_profile": _AI_ENGINEER_PROFILE,
            "job_requirements": RuntimeError("OpenAI is unreachable"),
        }
    )
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.MATCHING_FAILED
    assert "OpenAI is unreachable" in (resume_row.failure_reason or "")
