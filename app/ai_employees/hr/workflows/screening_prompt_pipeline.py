"""Auto-generated, per-screening AI screening prompt (spec sections 2-4).

Generated lazily on first view of a candidate's screening (not automatically
on approve-for-screening) to avoid spending LLM tokens on candidates HR
never opens. Fails loudly rather than falling back to a generic/fake
prompt: if generation fails or returns a blank/incomplete section, the
caller must surface the failure and block "Start Screening" — never
silently substitute fabricated or generic content.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.ai.provider import get_hr_llm_provider
from app.ai_employees.hr.models.screening import Screening
from app.ai_employees.hr.repositories.assessment_repository import AssessmentRepository
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.resume_repository import ResumeRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.schemas.screening_prompt import (
    SCREENING_PROMPT_SECTIONS_JSON_SCHEMA,
    SCREENING_PROMPT_SYSTEM_PROMPT,
    ScreeningPromptSections,
)
from app.core.config import get_settings
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppError, NotFoundError


class ScreeningPromptGenerationError(AppError):
    """Raised on any failure to produce a real, grounded prompt — the caller
    must surface this to HR and block Start Screening, never fall back to a
    generic/fake prompt (explicit product requirement).
    """

    status_code = 502
    code = ErrorCode.INTERNAL_ERROR


async def generate_screening_prompt(
    session: AsyncSession, *, organization_id: str, screening_id: str
) -> Screening:
    screening_repo = ScreeningRepository(session)
    candidate_repo = CandidateRepository(session)
    identity_repo = CandidateIdentityRepository(session)
    job_repo = JobRepository(session)
    resume_repo = ResumeRepository(session)
    assessment_repo = AssessmentRepository(session)

    screening = await screening_repo.get_by_id(organization_id, screening_id)
    if screening is None:
        raise NotFoundError("Screening not found.")

    candidate = await candidate_repo.get_by_id(organization_id, screening.candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found.")
    identity = await identity_repo.get_by_id(organization_id, candidate.identity_id)
    if identity is None:
        raise NotFoundError("Candidate identity not found.")
    job = await job_repo.get_by_id(organization_id, candidate.job_id)
    if job is None:
        raise NotFoundError("Job not found.")

    resume = await resume_repo.get_for_candidate(organization_id, candidate.id)
    assessment = await assessment_repo.get_latest_for_candidate(organization_id, candidate.id)
    # Per-job override (HR sets this when creating the job) takes priority
    # over the org-wide default — same pattern as job.company_name.
    persona_name = job.ai_agent_name or get_settings().hr_screening_persona_name

    user_content = json.dumps(
        {
            "agentName": persona_name,
            "job": {
                "title": job.title,
                "companyName": job.company_name,
                "description": job.description,
                "requirements": job.requirements,
            },
            "candidate": {
                "fullName": identity.full_name,
                "profile": resume.extracted_profile if resume else None,
            },
            "jdMatchEvidence": (
                {
                    "missingRequirements": assessment.missing_requirements,
                    "evidence": assessment.evidence,
                }
                if assessment
                else None
            ),
        }
    )

    llm_provider = get_hr_llm_provider()
    try:
        raw = await llm_provider.extract_structured(
            system_prompt=SCREENING_PROMPT_SYSTEM_PROMPT,
            user_content=user_content,
            json_schema=SCREENING_PROMPT_SECTIONS_JSON_SCHEMA,
            schema_name="screening_prompt_sections",
        )
        sections = ScreeningPromptSections.model_validate(raw)
    except Exception as exc:
        raise ScreeningPromptGenerationError(f"Screening prompt generation failed: {exc}") from exc

    _assert_sections_non_blank(sections)

    prompt_text = render_prompt_sections(
        sections,
        candidate_name=identity.full_name,
        job_title=job.title,
        company_name=job.company_name,
        agent_name=persona_name,
    )

    now = datetime.now(UTC)
    screening.prompt_text = prompt_text
    screening.prompt_generated_at = now
    history = list(screening.prompt_history or [])
    history.append(
        {
            "promptText": prompt_text,
            "editedAt": now.isoformat(),
            "editedByUserId": None,
            "source": "generated",
        }
    )
    screening.prompt_history = history
    return screening


def _assert_sections_non_blank(sections: ScreeningPromptSections) -> None:
    required_text_fields = {
        "screeningObjective": sections.screening_objective,
        "opening": sections.opening,
        "candidateBackground": sections.candidate_background,
        "compensation": sections.compensation,
        "availability": sections.availability,
        "closing": sections.closing,
    }
    blank = [name for name, value in required_text_fields.items() if not (value or "").strip()]
    if blank:
        raise ScreeningPromptGenerationError(
            f"Screening prompt generation returned blank section(s): {', '.join(blank)}."
        )
    if not sections.jd_questions:
        raise ScreeningPromptGenerationError(
            "Screening prompt generation returned no JD-specific questions."
        )


_CONVERSATION_STYLE = (
    "You are NOT a generic AI voice assistant, and you must never sound "
    "like one. You are the specific HR recruiter named in the 'AI Agent' "
    "section below, calling on behalf of the company named there, to "
    "conduct a real recruiting phone screening. Never say things like "
    "\"I'm an AI assistant,\" \"How can I assist you today?\", or \"Yes, I "
    "can hear you loud and clear\" — those are generic assistant replies "
    "and are wrong for this call.\n\n"
    "Do NOT speak first. This is an outbound phone call — wait in silence "
    "until the candidate answers and says something first (e.g. \"Hello?\"). "
    "Whatever the candidate says first is simply them picking up the phone "
    "— it is your cue to start, not a question directed at you and not "
    "something to react to. The very first thing you say, no matter what "
    "the candidate's first words were, must be your Opening introduction "
    "below (in your own natural words, not read verbatim) — introducing "
    "yourself by name and company and confirming who you're speaking with. "
    "Never start talking the instant the call connects, and never respond "
    "to the candidate's first words with a generic greeting or offer to "
    "help instead of your introduction.\n\n"
    "Speak naturally, like a real HR screener on a phone call — never read "
    "this as a numbered list or announce section names aloud. Adapt to "
    "what the candidate has already told you: if they've already answered "
    "something naturally (e.g. mentioned their experience while "
    "introducing themselves), do not ask that same question again. Keep "
    "the whole call to roughly five minutes — end once the required "
    "information below has been collected and the conversation reaches a "
    "natural conclusion, not on a fixed timer. If the candidate gives a "
    "long or off-topic answer, politely and briefly steer back to the "
    "screening."
)

_SPECIAL_SITUATIONS = (
    "If the candidate says they're busy, in a meeting, or can't talk right "
    "now: do NOT continue with screening questions. Respond warmly, e.g. "
    "\"No problem at all, thank you for letting me know — we'll follow up "
    "at a better time. Have a great day,\" then end the call politely. "
    "This is a normal outcome, not a failure.\n"
    "If the candidate asks something outside this screening's scope "
    "(exact salary bands, company policy, full interview process, etc.): "
    "do not invent an answer. Say something like \"That's something our "
    "HR team can clarify with you directly — I'll make a note of it,\" "
    "then return to the screening."
)


def render_prompt_sections(
    sections: ScreeningPromptSections,
    *,
    candidate_name: str,
    job_title: str,
    company_name: str | None,
    agent_name: str,
) -> str:
    """Deterministic rendering into the fixed structure (spec section 3) —
    section order/headers are never left to model formatting. The
    Conversation Style and Special Situations sections are fixed (not
    LLM-generated): universal call-handling behavior shouldn't vary
    candidate-to-candidate or depend on generation quality.
    """
    jd_questions = "\n".join(
        f"- Requirement: {q.requirement}\n  Question: {q.question}" for q in sections.jd_questions
    )
    candidate_questions = (
        "\n".join(f"- {q}" for q in sections.candidate_questions)
        if sections.candidate_questions
        else "- (No candidate-specific gaps identified — cover general background only.)"
    )
    company_line = company_name or "the company"

    return (
        "## Candidate\n"
        f"Name: {candidate_name}\n"
        f"Role: {job_title}\n"
        f"Company: {company_line}\n\n"
        "## AI Agent (Your Identity — Introduce Yourself This Way)\n"
        f"Name: {agent_name}\n"
        f"Calling On Behalf Of: {company_line}\n\n"
        f"## Screening Objective\n{sections.screening_objective}\n\n"
        f"## Conversation Style\n{_CONVERSATION_STYLE}\n\n"
        f"## Opening\n{sections.opening}\n\n"
        f"## Candidate Background\n{sections.candidate_background}\n\n"
        f"## JD-Specific Questions\n{jd_questions}\n\n"
        f"## Candidate-Specific Questions\n{candidate_questions}\n\n"
        f"## Compensation\n{sections.compensation}\n\n"
        f"## Availability\n{sections.availability}\n\n"
        f"## Handling Special Situations\n{_SPECIAL_SITUATIONS}\n\n"
        f"## Closing\n{sections.closing}\n"
    )
