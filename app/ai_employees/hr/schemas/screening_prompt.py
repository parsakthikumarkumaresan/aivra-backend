"""Auto-generated AI screening prompt (spec sections 2-4).

The LLM only produces the *content* of each section as structured JSON —
never free-form text — so the fixed section order and "never blank" rule
(spec section 3) are enforced deterministically in Python (see
screening_prompt_pipeline.py's ``render_prompt_sections``) rather than
trusted from model formatting.
"""

from __future__ import annotations

from app.shared.schemas.base import CamelModel

SCREENING_PROMPT_SYSTEM_PROMPT = (
    "You are drafting the content for an AI phone-screening conversation "
    "between an HR screening assistant and a job candidate. Ground every "
    "question in the actual job requirements and the candidate's actual "
    "resume evidence provided to you — never invent skills, projects, or "
    "experience the candidate profile does not support. JD-specific "
    "questions must reference the specific requirement being probed; "
    "candidate-specific questions must reference specific evidence from "
    "the candidate's profile (skills, work history, or prior JD-match "
    "evidence). Keep every field concise and natural to say aloud — this "
    "is a short initial screening (~5 minutes), not a technical interview. "
    "Write every field as natural spoken language, never as a numbered "
    "list or a bare question label.\n\n"
    "You are given the AI agent's configured display name, the company "
    "name, the candidate's name, and the job title. The 'opening' field is "
    "what the agent says ONLY AFTER the candidate has already answered the "
    "phone and spoken first (e.g. said \"Hello?\") — it must naturally "
    "introduce the agent BY that exact name and company (e.g. \"Hi, this "
    "is {agentName} calling from {companyName}. Am I speaking with "
    "{candidateName}?\"), then briefly explain the purpose and ask "
    "permission for a short conversation — do not skip the identity "
    "confirmation or the permission ask. The 'availability' field must "
    "cover BOTH notice period/joining timeline AND whether the candidate "
    "would be available for a follow-up human interview soon (e.g. this "
    "week) — phrase both naturally, not as a checklist."
)


class JdScreeningQuestion(CamelModel):
    requirement: str
    question: str


class ScreeningPromptSections(CamelModel):
    screening_objective: str
    opening: str
    candidate_background: str
    jd_questions: list[JdScreeningQuestion]
    candidate_questions: list[str]
    compensation: str
    availability: str
    closing: str


SCREENING_PROMPT_SECTIONS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "screeningObjective": {"type": "string"},
        "opening": {"type": "string"},
        "candidateBackground": {"type": "string"},
        "jdQuestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["requirement", "question"],
                "additionalProperties": False,
            },
        },
        "candidateQuestions": {"type": "array", "items": {"type": "string"}},
        "compensation": {"type": "string"},
        "availability": {"type": "string"},
        "closing": {"type": "string"},
    },
    "required": [
        "screeningObjective",
        "opening",
        "candidateBackground",
        "jdQuestions",
        "candidateQuestions",
        "compensation",
        "availability",
        "closing",
    ],
    "additionalProperties": False,
}
