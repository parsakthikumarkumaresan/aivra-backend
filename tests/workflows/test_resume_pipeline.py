"""Direct tests of the resume processing pipeline (spec section 9.2) —
covers the full happy path, a failure at each AI stage, and resumability
after a retry (the bug this module's design specifically had to avoid, see
app/ai_employees/hr/workflows/resume_pipeline.py docstring).
"""

from __future__ import annotations

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
from app.identity.models.user import User
from app.organizations.models.organization import Organization
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


async def _seed_org_job(db_session: AsyncSession) -> tuple[Organization, HrJob]:
    org = Organization(name="Acme", slug="acme-pipeline-test")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email="hr@example.com", password_hash=hash_password("SuperSecret123!"), full_name="HR Admin"
    )
    db_session.add(user)
    await db_session.flush()

    job = HrJob(
        organization_id=org.id,
        created_by_user_id=user.id,
        title="Backend Engineer",
        requirements=["5+ years Python", "Kubernetes"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()
    return org, job


async def _upload_resume(db_session: AsyncSession, org: Organization, job: HrJob):
    service = ResumeService(
        ResumeRepository(db_session),
        CandidateRepository(db_session),
        JobRepository(db_session),
        ProcessingJobRepository(db_session),
        FakeObjectStorage(),
    )
    candidate, resume, processing_job = await service.upload_resume(
        organization_id=org.id,
        job_id=job.id,
        filename="resume.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 fake resume bytes",
        candidate_name="Jane Doe",
        candidate_email="jane@example.com",
    )
    return candidate, resume, processing_job, service.storage


async def _latest_processing_job(db_session: AsyncSession, resume_id: str) -> ProcessingJob:
    stmt = (
        select(ProcessingJob)
        .where(ProcessingJob.resume_id == resume_id)
        .order_by(ProcessingJob.created_at.desc())
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
    candidate, resume, _processing_job, storage = await _upload_resume(db_session, org, job)

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

    candidate_row = await CandidateRepository(db_session).get_by_id(org.id, candidate.id)
    assert candidate_row is not None
    # MATCHED is a momentary waypoint — matching immediately makes the
    # candidate actionable for HR, so it lands on HR_REVIEW (spec section 9.1).
    assert candidate_row.stage == CandidateStage.HR_REVIEW

    assessment = await AssessmentRepository(db_session).get_latest_for_candidate(
        org.id, candidate.id
    )
    assert assessment is not None
    assert assessment.kind == AssessmentKind.JD_MATCH
    assert float(assessment.overall_score) == 88.0
    assert assessment.missing_requirements == ["Kubernetes"]

    assert llm.calls == ["resume_profile", "jd_match_result"]


async def test_resume_pipeline_extraction_failure_sets_failure_state(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, job = await _seed_org_job(db_session)
    _candidate, resume, _processing_job, storage = await _upload_resume(db_session, org, job)

    llm = FakeLLMProvider({"resume_profile": RuntimeError("OpenAI is unreachable")})
    _patch_providers(monkeypatch, storage, llm)

    await resume_pipeline.run_resume_pipeline(
        db_session, organization_id=org.id, resume_id=resume.id
    )

    resume_row = await ResumeRepository(db_session).get_by_id(org.id, resume.id)
    assert resume_row is not None
    assert resume_row.status == ResumeProcessingStatus.EXTRACTION_FAILED
    assert "OpenAI is unreachable" in (resume_row.failure_reason or "")


async def test_resume_pipeline_resumes_from_matching_after_retry(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this design had to avoid: a retry re-entering at MATCHING
    must not depend on EXTRACTING having run in the *same* call — the
    profile has to be reloaded from the persisted Resume row.
    """
    org, job = await _seed_org_job(db_session)
    candidate, resume, _processing_job, storage = await _upload_resume(db_session, org, job)

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
    # The retry never called resume_profile again — profile was reloaded
    # from resume.extracted_profile, not recomputed.
    assert working_llm.calls == ["jd_match_result"]

    latest_job_run = await _latest_processing_job(db_session, resume.id)
    assert latest_job_run.status == ProcessingJobStatus.SUCCEEDED
    assert latest_job_run.attempts == 2  # one failed run, one successful retry
