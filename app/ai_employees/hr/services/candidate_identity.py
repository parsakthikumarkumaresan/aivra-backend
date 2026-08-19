"""Shared candidate-identity logic used by both the automated resume
pipeline (app.ai_employees.hr.workflows.resume_pipeline) and the manual
HR identity-confirmation path (ResumeService.confirm_identity) — one
validation rule set and one creation path so both routes into a Candidate
row behave identically.

AI-extracted identity is untrusted input (it can be missing, malformed, or
just wrong) — every field here is business-validated before it is ever used
to create a CandidateIdentity, on top of the schema validation extraction.py
already does on shape/types.

Two-step creation mirrors the real-world model: a *person* (CandidateIdentity)
is reusable across every job they apply to; a *Candidate* is that person's
recruitment relationship with one specific job. Rejecting them for one job
must never affect any other job's Candidate row for the same person.
"""

from __future__ import annotations

import re

from app.ai_employees.hr.models.candidate import (
    Candidate,
    CandidateIdentity,
    CandidateSource,
    CandidateStage,
)
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def identity_issues(*, full_name: str, email: str) -> list[str]:
    issues: list[str] = []
    if not full_name.strip():
        issues.append("No candidate name is available.")
    if not email.strip() or not _EMAIL_PATTERN.match(email.strip()):
        issues.append("No valid candidate email is available.")
    return issues


async def get_or_create_identity(
    identity_repo: CandidateIdentityRepository,
    *,
    organization_id: str,
    full_name: str,
    email: str,
    phone: str | None,
) -> tuple[CandidateIdentity, bool]:
    """Returns (identity, created). Reuses an existing person identity for
    the same organization+email rather than creating a duplicate — and,
    once a person's identity exists, does NOT let a later AI extraction
    silently overwrite it (an HR-corrected or previously-confirmed identity
    is authoritative; only the explicit correction endpoint may change it).
    """
    existing = await identity_repo.find_by_email(organization_id, email.strip())
    if existing is not None:
        return existing, False

    identity = await identity_repo.add(
        CandidateIdentity(
            organization_id=organization_id,
            full_name=full_name.strip(),
            email=email.strip(),
            phone=phone,
        )
    )
    return identity, True


async def get_or_create_candidate(
    candidate_repo: CandidateRepository,
    *,
    organization_id: str,
    job_id: str,
    identity_id: str,
    source: CandidateSource,
) -> tuple[Candidate, bool]:
    """Returns (candidate, created). Scoped by (organization, job, identity)
    — the same person re-uploaded for the *same* job reuses the existing
    Candidate (application) untouched (its stage, including REJECTED, is
    never reset here — see resume_pipeline.py's PROCESSING-only auto-advance
    guard and CandidateService.reconsider for the explicit human action that
    is the only way out of REJECTED). The same person applying to a
    *different* job always gets its own, independent Candidate row.
    """
    existing = await candidate_repo.find_by_job_and_identity(organization_id, job_id, identity_id)
    if existing is not None:
        return existing, False

    candidate = await candidate_repo.add(
        Candidate(
            organization_id=organization_id,
            job_id=job_id,
            identity_id=identity_id,
            source=source,
            # OCR/parsing/extraction already ran by the time a Candidate can
            # exist under this flow — NEW would misrepresent where the
            # pipeline actually is (see resume_pipeline.py).
            stage=CandidateStage.PROCESSING,
        )
    )
    return candidate, True
