"""The async resume processing pipeline (spec section 9.2) — runs on the
background worker (app.workers.jobs.hr_resume_jobs), never inline with the
HTTP request.

Resume-first: HR uploads a file against a job, nothing else. The Candidate
does not exist yet at upload time — it is created here, by this pipeline,
only after AI extraction produces a name/email that passes business
validation (app.ai_employees.hr.services.candidate_identity). If extraction
can't produce usable identity, the resume pauses in NEEDS_IDENTITY_REVIEW
with the extracted evidence retained, and a human (via
ResumeService.confirm_identity) supplies/corrects it — the pipeline never
invents a name or synthesizes an email.

Resumable by design: every stage is gated on the resume's *current*
``status``, so re-invoking this function after a retry (which resets status
to the failed stage's entry point — see ``RESUME_TRANSITIONS``) continues
from exactly where it left off. The extracted profile is persisted on the
Resume row (not held as a local variable) precisely so a retry that
re-enters at MATCHING can reload it without re-running EXTRACTING. Candidate
creation is similarly idempotent: it only happens when ``resume.candidate_id``
is still unset, so a retry that re-enters at EXTRACTING after a crash (which
never committed a partial candidate — see hr_resume_jobs.py, one commit per
run) creates at most one Candidate per resume.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.ai.provider import get_hr_llm_provider
from app.ai_employees.hr.models.assessment import Assessment, AssessmentKind
from app.ai_employees.hr.models.candidate import (
    CANDIDATE_TRANSITIONS,
    Candidate,
    CandidateSource,
    CandidateStage,
)
from app.ai_employees.hr.models.job import HrJob
from app.ai_employees.hr.models.processing_job import ProcessingJob, ProcessingJobStatus
from app.ai_employees.hr.models.resume import RESUME_TRANSITIONS, Resume, ResumeProcessingStatus
from app.ai_employees.hr.repositories.assessment_repository import AssessmentRepository
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.resume_repository import ResumeRepository
from app.ai_employees.hr.schemas.assessment import (
    JD_MATCH_RESULT_JSON_SCHEMA,
    MODEL_VERSION,
    PROMPT_VERSION,
    RUBRIC_VERSION,
    JdMatchResult,
)
from app.ai_employees.hr.schemas.extraction import (
    EXTRACTED_RESUME_PROFILE_JSON_SCHEMA,
    ExtractedResumeProfile,
)
from app.ai_employees.hr.schemas.job_requirements import (
    JOB_REQUIREMENTS_JSON_SCHEMA,
    JOB_REQUIREMENTS_SYSTEM_PROMPT,
    JobRequirementsExtraction,
)
from app.ai_employees.hr.services.candidate_identity import get_or_create_candidate, identity_issues
from app.core.logging import get_logger
from app.shared.ai_providers.factory import get_ocr_provider
from app.shared.storage.factory import StorageCategory, get_object_storage

logger = get_logger(__name__)

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured candidate profile data from resume text. "
    "Only use information present in the text; do not invent details."
)
_MATCHING_SYSTEM_PROMPT = (
    "You score how well a candidate profile matches a job's requirements. "
    "You are given the structured requirements list, the job's free-text "
    "description for context, and the candidate's extracted profile "
    "(skills, experience, work history, education). "
    "For every requirement, state whether it is matched and cite evidence "
    "from the candidate profile. List requirements with no supporting "
    "evidence under missingRequirements. Scores are 0-100.\n\n"
    "Match on meaning, not exact string equality — a candidate's listed "
    "skills are often specific technologies or products that satisfy a more "
    "general requirement. For example: a named LLM/vendor (OpenAI, Gemini, "
    "Claude, AWS Bedrock) satisfies an 'LLM experience' requirement; a "
    "vector-capable datastore (pgvector, FAISS, Pinecone, or a vector "
    "database mentioned generically) satisfies a 'vector database' "
    "requirement; frameworks like LangChain or LangGraph satisfy an "
    "'AI Agents' or 'LLM orchestration' requirement; 'REST APIs' or "
    "'API Integration' satisfy a 'REST API development' requirement; "
    "'Multi-Agent Systems' satisfies an 'AI Agents' requirement. Use this "
    "kind of reasonable, evidence-backed inference throughout — do not "
    "require an exact substring match, but do not credit a requirement "
    "the candidate's profile gives no real support for either."
)


class _StageFailure(Exception):
    def __init__(self, failure_status: ResumeProcessingStatus, message: str) -> None:
        super().__init__(message)
        self.failure_status = failure_status
        self.message = message


def _transition(resume: Resume, target: ResumeProcessingStatus) -> None:
    RESUME_TRANSITIONS.assert_transition_allowed(resume.status, target)
    resume.status = target


def _transition_candidate(candidate: Candidate, target: CandidateStage) -> None:
    CANDIDATE_TRANSITIONS.assert_transition_allowed(candidate.stage, target)
    candidate.stage = target


async def run_resume_pipeline(
    session: AsyncSession, *, organization_id: str, resume_id: str
) -> None:
    resume_repo = ResumeRepository(session)
    candidate_repo = CandidateRepository(session)
    job_repo = JobRepository(session)
    assessment_repo = AssessmentRepository(session)

    resume = await resume_repo.get_by_id(organization_id, resume_id)
    if resume is None:
        logger.warning("resume_pipeline_resume_not_found", resume_id=resume_id)
        return
    job = await job_repo.get_by_id(organization_id, resume.job_id)
    if job is None:
        logger.warning("resume_pipeline_job_not_found", resume_id=resume_id)
        return

    candidate: Candidate | None = None
    if resume.candidate_id is not None:
        candidate = await candidate_repo.get_by_id(organization_id, resume.candidate_id)

    try:
        _run_stages(resume)
        await _run_ocr_stage(resume)
        _run_parsing_stage(resume)
        candidate = await _run_extraction_stage(
            resume, candidate=candidate, candidate_repo=candidate_repo, job_id=job.id
        )

        if resume.status == ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW:
            # Not a failure — OCR and extraction both succeeded; the pipeline
            # is correctly paused for a human to supply/correct identity via
            # ResumeService.confirm_identity. Also the correct outcome if
            # this run was triggered again while already stuck here.
            logger.info(
                "resume_pipeline_needs_identity_review",
                resume_id=resume_id,
                reason=resume.failure_reason,
            )
            await _mark_job_outcome(
                session, resume_id, ProcessingJobStatus.NEEDS_REVIEW, resume.failure_reason
            )
            return

        await _run_normalizing_stage(resume)

        if resume.status == ResumeProcessingStatus.MATCHING:
            if candidate is None:
                # Only reachable if the state machine and the data have
                # drifted apart (identity validation always creates a
                # candidate before advancing past EXTRACTING) — fail loudly
                # rather than silently score a match with nothing to attach.
                raise _StageFailure(
                    ResumeProcessingStatus.EXTRACTION_FAILED,
                    "Resume reached MATCHING with no associated candidate.",
                )
            await _run_matching_stage(resume, candidate, job, assessment_repo)

        await _mark_job_outcome(session, resume_id, ProcessingJobStatus.SUCCEEDED, None)
    except _StageFailure as failure:
        _transition(resume, failure.failure_status)
        resume.failure_reason = failure.message
        logger.warning(
            "resume_pipeline_stage_failed",
            resume_id=resume_id,
            status=failure.failure_status,
            error=failure.message,
        )
        await _mark_job_outcome(session, resume_id, ProcessingJobStatus.FAILED, failure.message)


def _run_stages(resume: Resume) -> None:
    if resume.status == ResumeProcessingStatus.UPLOADED:
        _transition(resume, ResumeProcessingStatus.VALIDATING)
    if resume.status == ResumeProcessingStatus.VALIDATING:
        _transition(resume, ResumeProcessingStatus.STORED)
    if resume.status == ResumeProcessingStatus.STORED:
        _transition(resume, ResumeProcessingStatus.OCR_PROCESSING)


async def _run_ocr_stage(resume: Resume) -> None:
    if resume.status != ResumeProcessingStatus.OCR_PROCESSING:
        return
    storage = get_object_storage(StorageCategory.DOCUMENTS)
    ocr_provider = get_ocr_provider()
    try:
        file_bytes = await storage.get_object(key=resume.storage_key)
        raw_text = await ocr_provider.extract_text(
            content=file_bytes, content_type=resume.content_type
        )
    except Exception as exc:  # any OCR/storage failure is retryable
        raise _StageFailure(
            ResumeProcessingStatus.PROCESSING_FAILED, f"OCR extraction failed: {exc}"
        ) from exc
    resume.extracted_text = raw_text
    _transition(resume, ResumeProcessingStatus.PARSING)


def _run_parsing_stage(resume: Resume) -> None:
    if resume.status != ResumeProcessingStatus.PARSING:
        return
    if not (resume.extracted_text or "").strip():
        raise _StageFailure(
            ResumeProcessingStatus.PROCESSING_FAILED,
            "No extractable text found in resume (scanned/image-only PDFs are not supported "
            "by the text-layer OCR provider — see app.shared.ai_providers.pdf_ocr_provider).",
        )
    _transition(resume, ResumeProcessingStatus.EXTRACTING)


async def _run_extraction_stage(
    resume: Resume,
    *,
    candidate: Candidate | None,
    candidate_repo: CandidateRepository,
    job_id: str,
) -> Candidate | None:
    """Runs AI extraction, then business-validates the extracted identity and
    creates the Candidate — the only place a Candidate gets created from a
    resume upload. Returns the candidate to use for the rest of the pipeline
    (unchanged from the argument when this stage doesn't run — i.e. a retry
    re-entering later than EXTRACTING).
    """
    if resume.status != ResumeProcessingStatus.EXTRACTING:
        return candidate

    llm_provider = get_hr_llm_provider()
    try:
        profile_raw = await llm_provider.extract_structured(
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            user_content=resume.extracted_text or "",
            json_schema=EXTRACTED_RESUME_PROFILE_JSON_SCHEMA,
            schema_name="resume_profile",
        )
        # Schema validation: shape/types only — this says nothing about
        # whether the values are *usable* as a candidate identity.
        profile = ExtractedResumeProfile.model_validate(profile_raw)
    except Exception as exc:
        raise _StageFailure(
            ResumeProcessingStatus.EXTRACTION_FAILED, f"Structured extraction failed: {exc}"
        ) from exc
    resume.extracted_profile = profile.model_dump(by_alias=True)

    # Business validation: the AI's output is untrusted input. A structurally
    # valid but empty/malformed name or email must not become a Candidate —
    # see app.ai_employees.hr.services.candidate_identity.
    issues = identity_issues(full_name=profile.full_name, email=profile.email)
    if issues:
        resume.failure_reason = "; ".join(issues)
        _transition(resume, ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW)
        return candidate

    if candidate is None:
        candidate, _created = await get_or_create_candidate(
            candidate_repo,
            organization_id=resume.organization_id,
            job_id=job_id,
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            source=CandidateSource.RESUME_UPLOAD,
        )
        resume.candidate_id = candidate.id
        candidate.resume_id = resume.id

    _transition(resume, ResumeProcessingStatus.NORMALIZING)
    return candidate


async def _run_normalizing_stage(resume: Resume) -> None:
    if resume.status != ResumeProcessingStatus.NORMALIZING:
        return
    if resume.extracted_profile is None:
        # EXTRACTING always sets this before transitioning to NORMALIZING —
        # reaching here with no profile means the state machine and the data
        # have drifted apart, which is a bug worth failing loudly on rather
        # than silently producing a match with no candidate data.
        raise _StageFailure(
            ResumeProcessingStatus.EXTRACTION_FAILED,
            "Resume is in NORMALIZING but has no extracted_profile.",
        )
    profile = ExtractedResumeProfile.model_validate(resume.extracted_profile)
    normalized_skills = sorted({s.strip().lower() for s in profile.skills if s.strip()})
    # Persist alongside the profile so MATCHING (a valid retry re-entry
    # point) can reload deterministic input without recomputing it —
    # cheap either way, but keeps this stage's output actually used.
    resume.extracted_profile = {**resume.extracted_profile, "normalizedSkills": normalized_skills}
    _transition(resume, ResumeProcessingStatus.MATCHING)


async def _ensure_job_requirements(job: HrJob) -> list[str]:
    """JD requirements extraction/normalization — a job created with only a
    free-text description (no structured requirements) has nothing for the
    matcher to score against unless this runs first. Derives requirements
    from the description via AI extraction and persists them onto the job
    (same session, flushed with the rest of the pipeline's changes) so every
    candidate matched against this job is scored against the *same*
    requirements list, not a freshly-reworded one per resume.
    """
    if job.requirements:
        return job.requirements
    if not (job.description or "").strip():
        return job.requirements  # nothing to derive from — genuinely no criteria exist

    llm_provider = get_hr_llm_provider()
    try:
        raw = await llm_provider.extract_structured(
            system_prompt=JOB_REQUIREMENTS_SYSTEM_PROMPT,
            user_content=job.description or "",
            json_schema=JOB_REQUIREMENTS_JSON_SCHEMA,
            schema_name="job_requirements",
        )
        extraction = JobRequirementsExtraction.model_validate(raw)
    except Exception as exc:
        raise _StageFailure(
            ResumeProcessingStatus.MATCHING_FAILED, f"JD requirements extraction failed: {exc}"
        ) from exc

    job.requirements = extraction.requirements
    return job.requirements


async def _run_matching_stage(
    resume: Resume, candidate: Candidate, job: HrJob, assessment_repo: AssessmentRepository
) -> None:
    if resume.status != ResumeProcessingStatus.MATCHING:
        return

    requirements = await _ensure_job_requirements(job)
    if not requirements:
        # A job with no structured requirements and no description to derive
        # them from cannot be meaningfully scored — a "0% match" here would
        # misrepresent "nothing to compare against" as "failed every check".
        raise _StageFailure(
            ResumeProcessingStatus.MATCHING_FAILED,
            "Job has no requirements and no description to derive them from — "
            "cannot score a match.",
        )

    llm_provider = get_hr_llm_provider()
    profile_data = resume.extracted_profile or {}
    normalized_skills = profile_data.get("normalizedSkills", [])

    try:
        match_raw = await llm_provider.extract_structured(
            system_prompt=_MATCHING_SYSTEM_PROMPT,
            user_content=json.dumps(
                {
                    "requirements": requirements,
                    "jobDescription": job.description,
                    "candidateProfile": profile_data,
                    "normalizedSkills": normalized_skills,
                }
            ),
            json_schema=JD_MATCH_RESULT_JSON_SCHEMA,
            schema_name="jd_match_result",
        )
        match_result = JdMatchResult.model_validate(match_raw)
    except Exception as exc:
        raise _StageFailure(
            ResumeProcessingStatus.MATCHING_FAILED, f"JD matching failed: {exc}"
        ) from exc

    await assessment_repo.add(
        Assessment(
            organization_id=resume.organization_id,
            candidate_id=candidate.id,
            kind=AssessmentKind.JD_MATCH,
            overall_score=match_result.overall_score,
            skill_match=match_result.skill_match,
            experience_match=match_result.experience_match,
            missing_requirements=match_result.missing_requirements,
            evidence=[e.model_dump(by_alias=True) for e in match_result.evidence],
            model_version=MODEL_VERSION,
            prompt_version=PROMPT_VERSION,
            rubric_version=RUBRIC_VERSION,
        )
    )
    _transition(resume, ResumeProcessingStatus.COMPLETED)
    # Scoring immediately makes the candidate actionable for HR (spec
    # section 9.1: "JD Matching -> Score + Evidence -> HR Approval") — MATCHED
    # is a momentary waypoint, not a queue state, so advance straight through
    # to HR_REVIEW. Only do this from PROCESSING: a duplicate/re-uploaded
    # resume for a candidate that's already further along (get_or_create_
    # candidate reused them — see candidate_identity.py) still gets scored
    # with a fresh Assessment, but must not force the candidate backward
    # through a stage transition the state machine doesn't allow.
    if candidate.stage == CandidateStage.PROCESSING:
        _transition_candidate(candidate, CandidateStage.MATCHED)
        _transition_candidate(candidate, CandidateStage.HR_REVIEW)


async def _mark_job_outcome(
    session: AsyncSession, resume_id: str, status: ProcessingJobStatus, error: str | None
) -> None:
    stmt = (
        select(ProcessingJob)
        .where(ProcessingJob.resume_id == resume_id)
        # id (ULID) sorts correctly by creation order even when created_at
        # ties — Postgres' now() is transaction-scoped, so two ProcessingJob
        # rows inserted in the same transaction (e.g. confirm_identity's
        # re-enqueue) get an identical created_at.
        .order_by(ProcessingJob.id.desc())
    )
    result = await session.execute(stmt)
    job_row = result.scalars().first()
    if job_row is None:
        return
    job_row.status = status
    job_row.attempts += 1
    job_row.last_error = error
    job_row.started_at = job_row.started_at or datetime.now(UTC)
    job_row.completed_at = datetime.now(UTC)
