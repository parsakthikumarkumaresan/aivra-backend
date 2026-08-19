from __future__ import annotations

from app.shared.schemas.base import CamelModel


class VoiceAnalyticsResponse(CamelModel):
    total_calls: int
    resolution_rate: float
    average_duration_seconds: float
    escalation_rate: float
    intent_breakdown: dict[str, int]
    outcome_breakdown: dict[str, int]
