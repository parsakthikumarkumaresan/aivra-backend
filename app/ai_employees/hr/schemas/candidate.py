from __future__ import annotations

from pydantic import EmailStr, Field

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


class UpdateCandidateIdentityRequest(CamelModel):
    """HR correcting AI-extracted identity during review (spec: 'HR Review /
    Correction'). All fields optional — send only what's being corrected.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
