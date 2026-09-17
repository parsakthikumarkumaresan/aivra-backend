"""Orchestrates app.ai_employees.voice.repositories.analytics_repository's
real SQL aggregations into the structured VoiceAnalyticsResponse. Owns:
date-range/timezone resolution, agent-ownership validation (never trusts a
client-supplied agent_id without checking it belongs to the requesting
org), and turning raw counts into the documented percentages/labels the
frontend renders — no numbers are invented here, only derived from what
the repository already computed in SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ai_employees.voice.repositories.analytics_repository import (
    MIN_ENGAGED_CUSTOMER_TURNS,
    MIN_ENGAGED_DURATION_SECONDS,
    AnalyticsFilters,
    VoiceAnalyticsRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.schemas.analytics import (
    AgentRow,
    AnalyticsMeta,
    CallDurationStats,
    CallerNumberRow,
    CallsOverTimePoint,
    ConnectRateAttempt,
    ConnectRateResponse,
    DispositionRow,
    DurationByStateRow,
    FunnelStage,
    HowCallsEndedRow,
    IntentRow,
    InterventionResponse,
    OutcomeRow,
    SummaryResponse,
    VoiceAnalyticsResponse,
    VoicemailStats,
)
from app.shared.errors.exceptions import NotFoundError, ValidationAppError

_END_REASON_LABELS = {
    "connected": "Connected",
    "customer_end": "Customer hung up",
    "agent_end": "Agent ended the call",
    "completed": "Completed",
    "system_shutdown": "System shutdown",
    "config_error": "Configuration error",
    "error": "Error",
    "room_closed": "Room closed",
    "voicemail": "Voicemail",
    "unknown": "Unknown",
}

_DURATION_STATE_LABELS = {
    "connected": "Connected",
    "human_answered": "Human answered",
    "no_response": "No response",
}

DATE_RANGES = ("today", "yesterday", "7d", "30d", "custom")


def _safe_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def resolve_date_range(
    date_range: str,
    tz_name: str,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolves a named range into UTC-aware [start, end) bounds, computed
    against the organization's real timezone so "Today"/"Yesterday" align
    with the org's actual local midnight, not UTC's."""
    tz = _safe_zone(tz_name)
    now_local = datetime.now(tz)
    start_of_today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if date_range == "today":
        start, end = start_of_today_local, start_of_today_local + timedelta(days=1)
    elif date_range == "yesterday":
        start = start_of_today_local - timedelta(days=1)
        end = start_of_today_local
    elif date_range == "7d":
        start = start_of_today_local - timedelta(days=6)
        end = start_of_today_local + timedelta(days=1)
    elif date_range == "30d":
        start = start_of_today_local - timedelta(days=29)
        end = start_of_today_local + timedelta(days=1)
    elif date_range == "custom":
        if start_date is None or end_date is None:
            raise ValidationAppError("startDate and endDate are required when dateRange=custom.")
        start = start_date if start_date.tzinfo else start_date.replace(tzinfo=tz)
        end = end_date if end_date.tzinfo else end_date.replace(tzinfo=tz)
        if end <= start:
            raise ValidationAppError("endDate must be after startDate.")
    else:
        raise ValidationAppError(f"Unknown dateRange {date_range!r}. Allowed: {DATE_RANGES}")

    return start.astimezone(UTC), end.astimezone(UTC)


def resolve_bucket(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= timedelta(days=2):
        return "hour"
    if span <= timedelta(days=35):
        return "day"
    return "week"


class VoiceAnalyticsService:
    def __init__(
        self, repo: VoiceAnalyticsRepository, agent_repo: VoiceAgentRepository
    ) -> None:
        self.repo = repo
        self.agent_repo = agent_repo

    async def get_analytics(
        self,
        *,
        organization_id: str,
        organization_timezone: str,
        date_range: str,
        agent_id: str | None,
        direction: str | None,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> VoiceAnalyticsResponse:
        if agent_id:
            agent = await self.agent_repo.get_by_id(organization_id, agent_id)
            if agent is None:
                raise NotFoundError("Voice agent not found for this organization.")

        start, end = resolve_date_range(
            date_range, organization_timezone, start_date=start_date, end_date=end_date
        )
        bucket = resolve_bucket(start, end)
        filters = AnalyticsFilters(
            organization_id=organization_id,
            start_date=start,
            end_date=end,
            agent_id=agent_id,
            direction=direction if direction and direction != "all" else None,
            bucket=bucket,
            timezone=organization_timezone,
        )

        funnel_raw = await self.repo.get_funnel(filters)
        calls_over_time_raw = await self.repo.get_calls_over_time(filters)
        disposition_raw = await self.repo.get_disposition(filters)
        how_ended_raw = await self.repo.get_how_calls_ended(filters)
        duration_stats_raw = await self.repo.get_call_duration_stats(filters)
        duration_by_state_raw = await self.repo.get_duration_by_state(filters)
        voicemail_raw = await self.repo.get_voicemail_stats(filters)
        outcomes_raw = await self.repo.get_outcomes(filters)
        intent_raw = await self.repo.get_intent_distribution(filters)
        by_number_raw = await self.repo.get_by_caller_number(filters)
        by_agent_raw = await self.repo.get_by_agent(filters)
        connect_rate_by_attempt_raw = await self.repo.get_connect_rate_by_attempt(filters)

        attempted = int(funnel_raw["attempted"])
        connected = int(funnel_raw["connected"])
        human_answered = int(funnel_raw["human_answered"])
        engaged = int(funnel_raw["engaged"])
        dialled = int(funnel_raw["dialled"])

        def pct(n: float, d: float) -> float:
            return round((n / d) * 100, 1) if d else 0.0

        funnel = [
            FunnelStage(
                key="attempted",
                label="Calls attempted",
                count=attempted,
                pct_of_attempted=100.0 if attempted else 0.0,
                description="Every call record in the selected range and filters.",
            ),
            FunnelStage(
                key="dialled",
                label="Calls dialled",
                count=dialled,
                pct_of_attempted=pct(dialled, attempted),
                description=(
                    "Jaan does not yet have a multi-attempt/retry dialer, so every "
                    "attempted call is also exactly one dial."
                ),
            ),
            FunnelStage(
                key="connected",
                label="Calls connected",
                count=connected,
                pct_of_attempted=pct(connected, attempted),
                description="The call room was created and did not fail (Call.status != 'failed').",
            ),
            FunnelStage(
                key="human_answered",
                label="Human answered",
                count=human_answered,
                pct_of_attempted=pct(human_answered, attempted),
                description=(
                    "Connected, and the transcript contains at least one real customer turn."
                ),
            ),
            FunnelStage(
                key="engaged",
                label="Engaged",
                count=engaged,
                pct_of_attempted=pct(engaged, attempted),
                description=(
                    f"Human-answered, lasted at least {MIN_ENGAGED_DURATION_SECONDS}s, and the "
                    f"customer spoke at least {MIN_ENGAGED_CUSTOMER_TURNS} times."
                ),
            ),
        ]

        calls_over_time = [
            CallsOverTimePoint(
                bucket_start=row["bucket_start"],
                attempted=int(row["attempted"]),
                dialled=int(row["dialled"]),
                connected=int(row["connected"]),
                human_answered=int(row["human_answered"]),
                engaged=int(row["engaged"]),
            )
            for row in calls_over_time_raw
        ]

        connect_rate = ConnectRateResponse(
            connected=connected,
            dialled=dialled,
            connect_rate=pct(connected, dialled),
            by_attempt=[
                ConnectRateAttempt(
                    attempt_number=int(r["attempt_number"]),
                    dialled=int(r["dialled"]),
                    connected=int(r["connected"]),
                    connect_rate=pct(r["connected"], r["dialled"]),
                )
                for r in connect_rate_by_attempt_raw
            ],
        )

        disposition = [
            DispositionRow(
                reason=r["reason"],
                label=_END_REASON_LABELS.get(r["reason"], r["reason"].replace("_", " ").title()),
                calls=int(r["calls"]),
                pct_of_attempted=pct(r["calls"], attempted),
            )
            for r in disposition_raw
        ]

        how_calls_ended = [
            HowCallsEndedRow(
                reason=r["reason"],
                label=_END_REASON_LABELS.get(r["reason"], r["reason"].replace("_", " ").title()),
                calls=int(r["calls"]),
                pct_of_connected=pct(r["calls"], connected),
            )
            for r in how_ended_raw
        ]

        call_duration = CallDurationStats(
            human_answered_calls=int(duration_stats_raw["human_answered_calls"]),
            average_seconds=float(duration_stats_raw["average_seconds"]),
            median_seconds=float(duration_stats_raw["median_seconds"]),
            p90_seconds=float(duration_stats_raw["p90_seconds"]),
            longest_seconds=float(duration_stats_raw["longest_seconds"]),
        )

        total_state_seconds = sum(float(r["total_seconds"]) for r in duration_by_state_raw) or 1.0
        duration_by_state = [
            DurationByStateRow(
                state=r["state"],
                label=_DURATION_STATE_LABELS.get(r["state"], r["state"]),
                calls=int(r["calls"]),
                pct_of_connected=pct(r["calls"], connected),
                avg_seconds=float(r["avg_seconds"]),
                total_seconds=float(r["total_seconds"]),
                pct_of_duration=round((float(r["total_seconds"]) / total_state_seconds) * 100, 1),
                # No sub-state transition timestamps are persisted yet
                # (Call only has started_at/ended_at) — true intra-call
                # state timing is not reconstructable, so it's flagged
                # rather than estimated. Connected/human_answered/
                # no_response are all real, transcript- and status-derived.
                not_enough_data=False,
            )
            for r in duration_by_state_raw
        ]

        voicemail = VoicemailStats(
            voicemail_calls=int(voicemail_raw["voicemail_calls"]),
            pct_of_connected=pct(voicemail_raw["voicemail_calls"], connected),
            duration_seconds=float(voicemail_raw["duration_seconds"]),
            detection_implemented=False,
            description=(
                "Voicemail/answering-machine detection is not yet implemented in the Jaan "
                "runtime, so this will always read zero until that detection is built — it is "
                "never estimated."
            ),
        )

        outcomes = [
            OutcomeRow(
                outcome=r["outcome"],
                calls=int(r["calls"]),
                pct_of_answered=pct(r["calls"], human_answered),
                avg_talk_time_seconds=float(r["avg_talk_time_seconds"]),
            )
            for r in outcomes_raw
        ]

        intent_total = sum(int(r["calls"]) for r in intent_raw) or 1
        intent_distribution = [
            IntentRow(intent=r["intent"], calls=int(r["calls"]), pct=pct(r["calls"], intent_total))
            for r in intent_raw
        ]

        where_to_intervene = InterventionResponse(
            by_caller_number=[
                CallerNumberRow(
                    number=r["number"],
                    attempted=int(r["attempted"]),
                    connect_rate=pct(r["connected"], r["attempted"]),
                    avg_duration_seconds=float(r["avg_duration_seconds"]),
                )
                for r in by_number_raw
            ],
            by_agent=[
                AgentRow(
                    agent_id=r["agent_id"],
                    agent_name=r["agent_name"],
                    attempted=int(r["attempted"]),
                    human_answered=int(r["human_answered"]),
                    engaged=int(r["engaged"]),
                    engaged_rate=pct(r["engaged"], r["human_answered"]),
                    avg_duration_seconds=float(r["avg_duration_seconds"]),
                )
                for r in by_agent_raw
            ],
        )

        missed = attempted - connected
        connected_seconds = sum(
            float(r["total_seconds"]) for r in duration_by_state_raw if r["state"] == "connected"
        )
        voice_minutes = round(connected_seconds / 60, 1)
        resolved_outcomes = {"resolved", "booked"}
        success_count = sum(
            int(r["calls"]) for r in outcomes_raw if r["outcome"] in resolved_outcomes
        )
        no_action_count = sum(int(r["calls"]) for r in outcomes_raw if r["outcome"] == "no_action")
        transfer_count = sum(int(r["calls"]) for r in outcomes_raw if r["outcome"] == "escalated")
        completion_rate = (
            pct(human_answered - no_action_count, human_answered) if human_answered else 0.0
        )

        summary = SummaryResponse(
            total_calls=attempted,
            connected_calls=connected,
            missed_calls=missed,
            voice_minutes=voice_minutes,
            average_duration_seconds=call_duration.average_seconds,
            success_rate=pct(success_count, human_answered),
            completion_rate=completion_rate,
            transfer_rate=pct(transfer_count, human_answered),
        )

        meta = AnalyticsMeta(
            organization_id=organization_id,
            agent_id=agent_id,
            direction=direction,
            date_range=date_range,
            start_date=start,
            end_date=end,
            bucket=bucket,
            timezone=organization_timezone,
        )

        return VoiceAnalyticsResponse(
            meta=meta,
            summary=summary,
            funnel=funnel,
            calls_over_time=calls_over_time,
            connect_rate=connect_rate,
            disposition=disposition,
            call_duration=call_duration,
            duration_by_state=duration_by_state,
            how_calls_ended=how_calls_ended,
            voicemail=voicemail,
            outcomes=outcomes,
            where_to_intervene=where_to_intervene,
            intent_distribution=intent_distribution,
        )
