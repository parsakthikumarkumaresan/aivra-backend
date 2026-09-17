from __future__ import annotations

from datetime import datetime

from app.shared.schemas.base import CamelModel


class AnalyticsMeta(CamelModel):
    organization_id: str
    agent_id: str | None
    direction: str | None
    date_range: str
    start_date: datetime
    end_date: datetime
    bucket: str
    timezone: str


class FunnelStage(CamelModel):
    key: str
    label: str
    count: int
    pct_of_attempted: float
    description: str


class CallsOverTimePoint(CamelModel):
    bucket_start: datetime
    attempted: int
    dialled: int
    connected: int
    human_answered: int
    engaged: int


class ConnectRateAttempt(CamelModel):
    attempt_number: int
    dialled: int
    connected: int
    connect_rate: float


class ConnectRateResponse(CamelModel):
    connected: int
    dialled: int
    connect_rate: float
    by_attempt: list[ConnectRateAttempt]


class DispositionRow(CamelModel):
    reason: str
    label: str
    calls: int
    pct_of_attempted: float


class CallDurationStats(CamelModel):
    human_answered_calls: int
    average_seconds: float
    median_seconds: float
    p90_seconds: float
    longest_seconds: float


class DurationByStateRow(CamelModel):
    state: str
    label: str
    calls: int
    pct_of_connected: float
    avg_seconds: float
    total_seconds: float
    pct_of_duration: float
    not_enough_data: bool = False


class HowCallsEndedRow(CamelModel):
    reason: str
    label: str
    calls: int
    pct_of_connected: float


class VoicemailStats(CamelModel):
    voicemail_calls: int
    pct_of_connected: float
    duration_seconds: float
    detection_implemented: bool
    description: str


class OutcomeRow(CamelModel):
    outcome: str
    calls: int
    pct_of_answered: float
    avg_talk_time_seconds: float


class CallerNumberRow(CamelModel):
    number: str
    attempted: int
    connect_rate: float
    avg_duration_seconds: float


class AgentRow(CamelModel):
    agent_id: str
    agent_name: str
    attempted: int
    human_answered: int
    engaged: int
    engaged_rate: float
    avg_duration_seconds: float


class InterventionResponse(CamelModel):
    by_caller_number: list[CallerNumberRow]
    by_agent: list[AgentRow]


class IntentRow(CamelModel):
    intent: str
    calls: int
    pct: float


class SummaryResponse(CamelModel):
    total_calls: int
    connected_calls: int
    missed_calls: int
    voice_minutes: float
    average_duration_seconds: float
    success_rate: float
    completion_rate: float
    transfer_rate: float


class VoiceAnalyticsResponse(CamelModel):
    meta: AnalyticsMeta
    summary: SummaryResponse
    funnel: list[FunnelStage]
    calls_over_time: list[CallsOverTimePoint]
    connect_rate: ConnectRateResponse
    disposition: list[DispositionRow]
    call_duration: CallDurationStats
    duration_by_state: list[DurationByStateRow]
    how_calls_ended: list[HowCallsEndedRow]
    voicemail: VoicemailStats
    outcomes: list[OutcomeRow]
    where_to_intervene: InterventionResponse
    intent_distribution: list[IntentRow]
