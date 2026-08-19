"""Resume upload — the synchronous half of the pipeline (spec section 9.2).

Validation and the actual storage write happen inline (the client is
already waiting on the upload); OCR/extraction/matching are queued for the
background worker (app.ai_employees.hr.workflows.resume_pipeline) so the
HTTP request never blocks on AI/document processing (spec section 28).
"""

from __future__ import annotations

from app.ai_employees.hr.models.candidate import Candidate, CandidateSource, CandidateStage
from app.ai_employees.hr.models.processing_job import ProcessingJob
from app.ai_employees.hr.models.resume import Resume, ResumeProcessingStatus
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.processing_job_repository import ProcessingJobRepository
from app.ai_employees.hr.repositories.resume_repository import ResumeRepository
from app.shared.errors.exceptions import ValidationAppError
from app.shared.storage.base import ObjectStorage, build_object_key

_MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = {"application/pdf"}


class ResumeService:
    def __init__(
        self,
        resume_repo: ResumeRepository,
        candidate_repo: CandidateRepository,
        job_repo: JobRepository,
        processing_job_repo: ProcessingJobRepository,
        storage: ObjectStorage,
    ) -> None:
        self.resume_repo = resume_repo
        self.candidate_repo = candidate_repo
        self.job_repo = job_repo
        self.processing_job_repo = processing_job_repo
        self.storage = storage

    async def upload_resume(
        self,
        *,
        organization_id: str,
        job_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        candidate_name: str,
        candidate_email: str,
        candidate_phone: str | None = None,
    ) -> tuple[Candidate, Resume, ProcessingJob]:
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise ValidationAppError(
                f"Unsupported file type: {content_type}. Only PDF is accepted."
            )
        if len(content) == 0:
            raise ValidationAppError("Uploaded file is empty.")
        if len(content) > _MAX_RESUME_SIZE_BYTES:
            raise ValidationAppError("Resume file exceeds the 10MB size limit.")

        await self.job_repo.get_by_id(organization_id, job_id)  # 404s via caller if missing

        candidate = await self.candidate_repo.add(
            Candidate(
                organization_id=organization_id,
                job_id=job_id,
                full_name=candidate_name,
                email=candidate_email,
                phone=candidate_phone,
                source=CandidateSource.RESUME_UPLOAD,
                stage=CandidateStage.NEW,
            )
        )

        key = build_object_key(
            organization_id=organization_id,
            category="resumes",
            object_id=candidate.id,
            filename=filename,
        )
        stored = await self.storage.put_object(key=key, content=content, content_type=content_type)

        resume = await self.resume_repo.add(
            Resume(
                organization_id=organization_id,
                candidate_id=candidate.id,
                storage_key=stored.key,
                original_filename=filename,
                content_type=content_type,
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                status=ResumeProcessingStatus.UPLOADED,
            )
        )
        candidate.resume_id = resume.id

        processing_job = await self.processing_job_repo.add(
            ProcessingJob(organization_id=organization_id, resume_id=resume.id)
        )

        return candidate, resume, processing_job
