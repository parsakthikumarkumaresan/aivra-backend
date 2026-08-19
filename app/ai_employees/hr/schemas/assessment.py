"""JD-match scoring output (spec section 9.3) — schema-validated before use,
same posture as extraction.py.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.shared.schemas.base import CamelModel

MODEL_VERSION = "gpt-4o-mini"
PROMPT_VERSION = "v1"
RUBRIC_VERSION = "v1"


class RequirementEvidence(CamelModel):
    requirement: str
    matched: bool
    evidence_text: str


class JdMatchResult(CamelModel):
    overall_score: float = Field(ge=0, le=100)
    skill_match: float = Field(ge=0, le=100)
    experience_match: float = Field(ge=0, le=100)
    missing_requirements: list[str]
    evidence: list[RequirementEvidence]


class AssessmentResponse(CamelModel):
    id: str
    candidate_id: str
    overall_score: float
    skill_match: float
    experience_match: float
    missing_requirements: list[str]
    evidence: list[dict]
    model_version: str
    prompt_version: str
    rubric_version: str
    created_at: datetime


JD_MATCH_RESULT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "overallScore": {"type": "number"},
        "skillMatch": {"type": "number"},
        "experienceMatch": {"type": "number"},
        "missingRequirements": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "matched": {"type": "boolean"},
                    "evidenceText": {"type": "string"},
                },
                "required": ["requirement", "matched", "evidenceText"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "overallScore",
        "skillMatch",
        "experienceMatch",
        "missingRequirements",
        "evidence",
    ],
    "additionalProperties": False,
}
