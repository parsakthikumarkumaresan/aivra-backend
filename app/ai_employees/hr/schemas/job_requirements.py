"""JD requirements extraction — turns a job's free-text description into a
structured, evaluable requirements list when HR didn't (or couldn't) supply
one explicitly. Same schema-validated-AI-output posture as extraction.py.

Without this step, a job created with only a description and no structured
``requirements`` sends an empty list into JD matching, which then has
nothing to score candidates against — see resume_pipeline.py's
``_ensure_job_requirements``.
"""

from __future__ import annotations

from app.shared.schemas.base import CamelModel

JOB_REQUIREMENTS_SYSTEM_PROMPT = (
    "You extract a concise, structured list of specific, evaluable job "
    "requirements (skills, technologies, tools, experience thresholds, "
    "responsibilities) from a free-text job description. Only include "
    "requirements the text actually implies — do not invent requirements "
    "not supported by the description. Return between 5 and 15 short "
    "requirement phrases, each specific enough that a resume could be "
    "checked against it individually."
)


class JobRequirementsExtraction(CamelModel):
    requirements: list[str]


JOB_REQUIREMENTS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["requirements"],
    "additionalProperties": False,
}
