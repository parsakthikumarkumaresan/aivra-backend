"""Resume upload — the synchronous half of the pipeline (spec section 9.2).

Validation and the actual storage write happen inline (the client is
already waiting on the upload); OCR/extraction/matching are queued for the
background worker (app.ai_employees.hr.workflows.resume_pipeline) so the
HTTP request never blocks on AI/document processing (spec section 28).

Resume-first: upload takes only a file + job — no candidate identity. The
Candidate is created later, by the pipeline, once AI extraction produces a
usable name/email (see candidate_identity.py); if it can't, the resume
pauses in NEEDS_IDENTITY_REVIEW and ``confirm_identity`` below is how HR
supplies/corrects it and lets the pipeline continue.
"""

from __future__ import annotations

from app.ai_employees.hr.models.candidate import Candidate, CandidateSource
from app.ai_employees.hr.models.processing_job import ProcessingJob
from app.ai_employees.hr.models.resume import RESUME_TRANSITIONS, Resume, ResumeProcessingStatus
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.processing_job_repository import ProcessingJobRepository
from app.ai_employees.hr.repositories.resume_repository import ResumeRepository
from app.ai_employees.hr.services.candidate_identity import (
    get_or_create_candidate,
    get_or_create_identity,
    identity_issues,
)
from app.audit.models.audit_event import ActorType
from app.audit.services.audit_service import AuditService
from app.shared.database.ids import IdPrefix, new_id
from app.shared.errors.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    ValidationAppError,
)
from app.shared.storage.base import ObjectStorage, build_object_key

_MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = {"application/pdf"}


class ResumeService:
    def __init__(
        self,
        resume_repo: ResumeRepository,
        candidate_repo: CandidateRepository,
        identity_repo: CandidateIdentityRepository,
        job_repo: JobRepository,
        processing_job_repo: ProcessingJobRepository,
        storage: ObjectStorage,
        audit: AuditService,
    ) -> None:
        self.resume_repo = resume_repo
        self.candidate_repo = candidate_repo
        self.identity_repo = identity_repo
        self.job_repo = job_repo
        self.processing_job_repo = processing_job_repo
        self.storage = storage
        self.audit = audit

    async def upload_resume(
        self,
        *,
        organization_id: str,
        job_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> tuple[Resume, ProcessingJob]:
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise ValidationAppError(
                f"Unsupported file type: {content_type}. Only PDF is accepted."
            )
        if len(content) == 0:
            raise ValidationAppError("Uploaded file is empty.")
        if len(content) > _MAX_RESUME_SIZE_BYTES:
            raise ValidationAppError("Resume file exceeds the 10MB size limit.")

        job = await self.job_repo.get_by_id(organization_id, job_id)
        if job is None:
            raise NotFoundError("Job not found.")

        resume_id = new_id(IdPrefix.RESUME)
        key = build_object_key(
            organization_id=organization_id,
            category="resumes",
            object_id=resume_id,
            filename=filename,
        )
        stored = await self.storage.put_object(key=key, content=content, content_type=content_type)

        resume = await self.resume_repo.add(
            Resume(
                id=resume_id,
                organization_id=organization_id,
                job_id=job_id,
                candidate_id=None,
                storage_key=stored.key,
                original_filename=filename,
                content_type=content_type,
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                status=ResumeProcessingStatus.UPLOADED,
            )
        )

        processing_job = await self.processing_job_repo.add(
            ProcessingJob(organization_id=organization_id, resume_id=resume.id)
        )

        return resume, processing_job

    async def confirm_identity(
        self,
        *,
        organization_id: str,
        resume_id: str,
        full_name: str,
        email: str,
        phone: str | None,
        actor_id: str,
    ) -> tuple[Candidate, Resume, ProcessingJob]:
        """HR supplies/corrects the candidate identity for a resume the
        pipeline could not confidently extract one for. Creates (or reuses,
        for a duplicate/re-uploaded resume) the Candidate and re-enqueues the
        pipeline to finish normalizing + matching.
        """
        resume = await self.resume_repo.get_by_id(organization_id, resume_id)
        if resume is None:
            raise NotFoundError("Resume not found.")
        if resume.status != ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW:
            raise InvalidStateTransitionError(
                f"Resume is not awaiting identity confirmation (status: {resume.status})."
            )

        issues = identity_issues(full_name=full_name, email=email)
        if issues:
            raise ValidationAppError("; ".join(issues))

        identity, _identity_created = await get_or_create_identity(
            self.identity_repo,
            organization_id=organization_id,
            full_name=full_name,
            email=email,
            phone=phone,
        )
        candidate, created = await get_or_create_candidate(
            self.candidate_repo,
            organization_id=organization_id,
            job_id=resume.job_id,
            identity_id=identity.id,
            source=CandidateSource.RESUME_UPLOAD,
        )
        RESUME_TRANSITIONS.assert_transition_allowed(
            resume.status, ResumeProcessingStatus.NORMALIZING
        )
        resume.candidate_id = candidate.id
        candidate.resume_id = resume.id
        resume.failure_reason = None
        resume.status = ResumeProcessingStatus.NORMALIZING

        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action=(
                "CANDIDATE_IDENTITY_CONFIRMED"
                if created
                else "CANDIDATE_IDENTITY_CONFIRMED_DUPLICATE_LINKED"
            ),
            resource_type="CANDIDATE",
            resource_id=candidate.id,
        )

        processing_job = await self.processing_job_repo.add(
            ProcessingJob(organization_id=organization_id, resume_id=resume.id)
        )
        return candidate, resume, processing_job
