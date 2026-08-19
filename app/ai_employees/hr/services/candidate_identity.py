"""Shared candidate-identity logic used by both the automated resume
pipeline (app.ai_employees.hr.workflows.resume_pipeline) and the manual
HR identity-confirmation path (ResumeService.confirm_identity) — one
validation rule set and one creation path so both routes into a Candidate
row behave identically.

AI-extracted identity is untrusted input (it can be missing, malformed, or
just wrong) — every field here is business-validated before it is ever used
to create a Candidate, on top of the schema validation extraction.py already
does on shape/types.
"""

from __future__ import annotations

import re

from app.ai_employees.hr.models.candidate import Candidate, CandidateSource, CandidateStage
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def identity_issues(*, full_name: str, email: str) -> list[str]:
    issues: list[str] = []
    if not full_name.strip():
        issues.append("No candidate name is available.")
    if not email.strip() or not _EMAIL_PATTERN.match(email.strip()):
        issues.append("No valid candidate email is available.")
    return issues


async def get_or_create_candidate(
    candidate_repo: CandidateRepository,
    *,
    organization_id: str,
    job_id: str,
    full_name: str,
    email: str,
    phone: str | None,
    source: CandidateSource,
) -> tuple[Candidate, bool]:
    """Returns (candidate, created). Reuses an existing candidate for the
    same job+email instead of creating a duplicate (handles re-uploaded/
    duplicate resumes and makes retrying this step idempotent).
    """
    existing = await candidate_repo.find_by_job_and_email(organization_id, job_id, email.strip())
    if existing is not None:
        return existing, False

    candidate = await candidate_repo.add(
        Candidate(
            organization_id=organization_id,
            job_id=job_id,
            full_name=full_name.strip(),
            email=email.strip(),
            phone=phone,
            source=source,
            # OCR/parsing/extraction already ran by the time a Candidate can
            # exist under this flow — NEW would misrepresent where the
            # pipeline actually is (see resume_pipeline.py).
            stage=CandidateStage.PROCESSING,
        )
    )
    return candidate, True
