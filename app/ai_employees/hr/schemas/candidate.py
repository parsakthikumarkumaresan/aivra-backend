from __future__ import annotations

from app.shared.schemas.base import CamelModel


class CandidateResponse(CamelModel):
    id: str
    job_id: str
    full_name: str
    email: str
    phone: str | None
    source: str
    stage: str
    resume_id: str | None
    rejected_reason: str | None


class CandidateDecisionRequest(CamelModel):
    note: str | None = None
