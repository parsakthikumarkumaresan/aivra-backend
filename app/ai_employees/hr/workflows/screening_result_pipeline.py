"""Structured screening result generation (spec section 14) — runs after a
call's transcript is finalized. Derives the result only from the actual
transcript + JD, never invents facts, and is advisory only (never an
autonomous hiring decision — HR always reviews and decides next steps).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.ai.provider import get_hr_llm_provider
from app.ai_employees.hr.models.job import HrJob
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.schemas.screening_result import (
    SCREENING_RESULT_JSON_SCHEMA,
    ScreeningResult,
)
from app.shared.errors.exceptions import NotFoundError

_RESULT_SYSTEM_PROMPT = (
    "You analyze a completed AI phone-screening call transcript for a job "
    "candidate and produce a structured, advisory summary for a human "
    "recruiter. Base every field ONLY on what is actually present in the "
    "transcript and the job's requirements — never invent facts, "
    "compensation figures, dates, or evidence the transcript does not "
    "support. If a topic (e.g. current CTC) was never discussed, leave the "
    "corresponding field null rather than guessing.\n\n"
    "Field guidance:\n"
    "- introduction: a one-sentence summary of how the candidate described "
    "themselves (role + experience), in the candidate's own terms.\n"
    "- currentRole / totalExperience / relevantExperience: only what the "
    "candidate actually stated.\n"
    "- interviewAvailability: when the candidate said they could do a human "
    "interview (e.g. 'this week', 'weekends only'), null if not discussed.\n"
    "- candidateInterest: a short phrase describing how interested the "
    "candidate seemed (e.g. 'Interested', 'Lukewarm', 'Not interested'), "
    "based only on what they actually said/how they responded.\n"
    "- keyObservations: 1-4 short, concrete observations a recruiter would "
    "find useful (communication clarity, notable strengths/concerns) — "
    "never speculation not grounded in the transcript.\n"
    "- recommendation: use 'candidate_unavailable' if the candidate said "
    "they couldn't talk right now / asked to be called back and the "
    "screening questions were never actually asked — this is NOT a "
    "technical failure, the call completed normally. Otherwise use "
    "'proceed'/'hold'/'reject' based on fit.\n\n"
    "Your recommendation is advisory only; a human always makes the final "
    "hiring call."
)


async def generate_screening_result(
    session: AsyncSession, *, organization_id: str, screening_id: str
) -> Screening:
    screening_repo = ScreeningRepository(session)
    candidate_repo = CandidateRepository(session)
    job_repo = JobRepository(session)

    screening = await screening_repo.get_by_id(organization_id, screening_id)
    if screening is None:
        raise NotFoundError("Screening not found.")

    transcript = screening.transcript or []
    if not transcript:
        # Fail loudly rather than silently marking a call with no captured
        # conversation as "completed" — see resume_pipeline.py's philosophy.
        screening.status = ScreeningStatus.FAILED
        screening.failure_reason = "Call ended with no transcript captured."
        return screening

    candidate = await candidate_repo.get_by_id(organization_id, screening.candidate_id)
    job: HrJob | None = (
        await job_repo.get_by_id(organization_id, candidate.job_id) if candidate else None
    )

    user_content = json.dumps(
        {
            "job": {
                "title": job.title if job else None,
                "requirements": job.requirements if job else [],
            },
            "transcript": transcript,
        }
    )

    llm_provider = get_hr_llm_provider()
    try:
        raw = await llm_provider.extract_structured(
            system_prompt=_RESULT_SYSTEM_PROMPT,
            user_content=user_content,
            json_schema=SCREENING_RESULT_JSON_SCHEMA,
            schema_name="screening_result",
        )
        result = ScreeningResult.model_validate(raw)
    except Exception as exc:
        screening.status = ScreeningStatus.FAILED
        screening.failure_reason = f"Screening result generation failed: {exc}"
        return screening

    screening.result = result.model_dump(by_alias=True)
    screening.result_summary = result.recommendation_rationale
    screening.status = ScreeningStatus.COMPLETED
    screening.completed_at = datetime.now(UTC)
    # Clear any failure_reason from an earlier stall/error on this same
    # screening row — a completed result must never show a stale failure.
    screening.failure_reason = None
    return screening
