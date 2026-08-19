from __future__ import annotations

from app.ai_employees.hr.schemas.candidate import CandidateResponse
from app.shared.schemas.base import CamelModel


class ResumeResponse(CamelModel):
    id: str
    candidate_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    failure_reason: str | None


class ProcessingJobResponse(CamelModel):
    id: str
    resume_id: str
    status: str
    attempts: int
    last_error: str | None


class UploadResumeResponse(CamelModel):
    candidate: CandidateResponse
    resume: ResumeResponse
    processing_job: ProcessingJobResponse
