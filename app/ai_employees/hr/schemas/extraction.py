"""Schema-validated AI extraction output (spec section 41).

The LLM is constrained to this exact JSON shape via OpenAI's structured-
output mode (see app.shared.ai_providers.openai_llm_provider), and the
result is *also* re-validated here via Pydantic before it is ever persisted
or used for a business decision — provider-level schema conformance is not
the same as business-rule validity.
"""

from __future__ import annotations

from app.shared.schemas.base import CamelModel


class WorkHistoryEntry(CamelModel):
    company: str
    title: str
    duration_months: int


class EducationEntry(CamelModel):
    institution: str
    degree: str


class ExtractedResumeProfile(CamelModel):
    full_name: str
    email: str
    phone: str
    skills: list[str]
    total_experience_years: float
    work_history: list[WorkHistoryEntry]
    education: list[EducationEntry]


EXTRACTED_RESUME_PROFILE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "fullName": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "totalExperienceYears": {"type": "number"},
        "workHistory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "durationMonths": {"type": "integer"},
                },
                "required": ["company", "title", "durationMonths"],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": "string"},
                },
                "required": ["institution", "degree"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "fullName",
        "email",
        "phone",
        "skills",
        "totalExperienceYears",
        "workHistory",
        "education",
    ],
    "additionalProperties": False,
}
