from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from app.shared.schemas.base import CamelModel


class CandidateResponse(CamelModel):
    """One person's recruitment relationship with one specific job — see
    app.ai_employees.hr.models.candidate for the Candidate/CandidateIdentity
    split this flattens back together for the API.
    """

    id: str
    identity_id: str
    job_id: str
    full_name: str
    email: str
    phone: str | None
    source: str
    stage: str
    resume_id: str | None
    rejected_reason: str | None
    archived_at: datetime | None
    archived_by_user_id: str | None


class CandidateDecisionRequest(CamelModel):
    note: str | None = None


class UpdateCandidateIdentityRequest(CamelModel):
    """HR correcting AI-extracted identity during review (spec: 'HR Review /
    Correction'). Applies to the person's identity, not just this one
    application, since it's the same underlying contact info everywhere.
    All fields optional — send only what's being corrected.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None


class BulkArchiveRequest(CamelModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=200)


class BulkArchiveResponse(CamelModel):
    archived: list[CandidateResponse]
    # candidate_id -> reason it couldn't be archived (not found, wrong tenant,
    # already archived) — never silently dropped.
    skipped: dict[str, str]
