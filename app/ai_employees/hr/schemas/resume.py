from __future__ import annotations

from pydantic import EmailStr, Field

from app.ai_employees.hr.schemas.candidate import CandidateResponse
from app.shared.schemas.base import CamelModel


class ResumeResponse(CamelModel):
    id: str
    job_id: str
    # Unset until AI extraction (or HR, via confirm-identity) establishes a
    # usable candidate identity — see ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW.
    candidate_id: str | None
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    failure_reason: str | None
    extracted_profile: dict | None = None


class ProcessingJobResponse(CamelModel):
    id: str
    resume_id: str
    status: str
    attempts: int
    last_error: str | None


class UploadResumeResponse(CamelModel):
    # No candidate yet at upload time — it's created by the pipeline once
    # extraction produces a usable identity (or later, via confirm-identity).
    resume: ResumeResponse
    processing_job: ProcessingJobResponse


class ConfirmIdentityRequest(CamelModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = None


class ConfirmIdentityResponse(CamelModel):
    candidate: CandidateResponse
    resume: ResumeResponse
    processing_job: ProcessingJobResponse
