"""Structured AI-screening-call outcome (spec section 14) — advisory only,
never an autonomous hiring decision. Same schema-validated-before-use
posture as extraction.py/assessment.py.
"""

from __future__ import annotations

from typing import Literal

from app.shared.schemas.base import CamelModel

MODEL_VERSION = "gpt-4o-mini"
PROMPT_VERSION = "v2"

# "candidate_unavailable" is distinct from the technical FAILED status on
# Screening itself — the call connected and completed normally, the
# candidate just wasn't able to talk right then (spec: never mark this as
# a technical failure).
ScreeningRecommendation = Literal["proceed", "hold", "reject", "candidate_unavailable"]


class ScreeningJdEvidence(CamelModel):
    requirement: str
    evidence: str
    transcript_ref: str | None = None


class ScreeningResult(CamelModel):
    recommendation: ScreeningRecommendation
    recommendation_rationale: str
    introduction: str | None = None
    current_role: str | None = None
    total_experience: str | None = None
    relevant_experience: str | None = None
    current_ctc: str | None = None
    expected_ctc: str | None = None
    notice_period: str | None = None
    immediate_availability: bool | None = None
    joining_date: str | None = None
    interview_availability: str | None = None
    candidate_interest: str | None = None
    key_observations: list[str] = []
    candidate_questions: list[str] = []
    gaps: list[str] = []
    jd_evidence: list[ScreeningJdEvidence] = []


SCREENING_RESULT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {
            "type": "string",
            "enum": ["proceed", "hold", "reject", "candidate_unavailable"],
        },
        "recommendationRationale": {"type": "string"},
        "introduction": {"type": ["string", "null"]},
        "currentRole": {"type": ["string", "null"]},
        "totalExperience": {"type": ["string", "null"]},
        "relevantExperience": {"type": ["string", "null"]},
        "currentCtc": {"type": ["string", "null"]},
        "expectedCtc": {"type": ["string", "null"]},
        "noticePeriod": {"type": ["string", "null"]},
        "immediateAvailability": {"type": ["boolean", "null"]},
        "joiningDate": {"type": ["string", "null"]},
        "interviewAvailability": {"type": ["string", "null"]},
        "candidateInterest": {"type": ["string", "null"]},
        "keyObservations": {"type": "array", "items": {"type": "string"}},
        "candidateQuestions": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "jdEvidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "evidence": {"type": "string"},
                    "transcriptRef": {"type": ["string", "null"]},
                },
                "required": ["requirement", "evidence", "transcriptRef"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "recommendation",
        "recommendationRationale",
        "introduction",
        "currentRole",
        "totalExperience",
        "relevantExperience",
        "currentCtc",
        "expectedCtc",
        "noticePeriod",
        "immediateAvailability",
        "joiningDate",
        "interviewAvailability",
        "candidateInterest",
        "keyObservations",
        "candidateQuestions",
        "gaps",
        "jdEvidence",
    ],
    "additionalProperties": False,
}
