from __future__ import annotations

from typing import Any

from app.shared.schemas.base import CamelModel

MODEL_VERSION = "gpt-4o-mini"
PROMPT_VERSION = "v1"


class CallAnalysisResult(CamelModel):
    intent_detected: str | None = None
    sentiment: str | None = None
    resolution_status: str | None = None
    summary: str | None = None
    key_topics: list[str] = []
    custom_fields: dict[str, Any] = {}


CALL_ANALYSIS_RESULT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intentDetected": {"type": "string"},
        "sentiment": {"type": "string"},
        "resolutionStatus": {"type": "string"},
        "summary": {"type": "string"},
        "keyTopics": {"type": "array", "items": {"type": "string"}},
        "customFields": {"type": "object"},
    },
    "required": [
        "intentDetected",
        "sentiment",
        "resolutionStatus",
        "summary",
        "keyTopics",
        "customFields",
    ],
    "additionalProperties": False,
}
