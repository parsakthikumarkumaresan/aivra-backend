"""Real, SQL-aggregated analytics for Jaan voice calls.

Every method here issues a targeted GROUP BY / COUNT / AVG /
percentile_cont query — never `SELECT *` followed by a Python loop. The
one exception, a per-call "how many customer turns are in this call's
transcript" figure, is computed inside a shared CTE via Postgres'
`jsonb_array_elements` (Transcript.turns is a JSON column, not a
normalized table) — still evaluated by Postgres, not Python, and reused as
a subquery by every method that needs it (funnel, calls-over-time,
duration-by-state).

This is intentionally a plain-SQL (`text()`) repository rather than
SQLAlchemy Core/ORM query-building: the aggregations involved (JSON
element unnesting, percentile_cont, multi-column GROUP BY with derived
CASE expressions) are significantly clearer to read and verify as SQL than
as chained Core expressions, and every value is bound (never
string-interpolated), so there is no injection surface — the same posture
already used for the one other raw-SQL call in this codebase
(app/api/v1/health.py's `SELECT 1`), just with real parameters this time.

ruff's S608 ("possible SQL injection via string-based query construction")
fires on every f-string below purely because it looks like SQL assembled
via an f-string; it cannot see that the only interpolated fragments are
static, code-controlled strings (`cte`, `where_sql`, a validated `bucket`
literal) and that every real value flows through bound `:param`
placeholders. Suppressed file-wide rather than per-line since the same
justification applies identically to every query in this module.
"""

# ruff: noqa: S608

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AnalyticsFilters:
    organization_id: str
    start_date: datetime
    end_date: datetime
    agent_id: str | None = None
    direction: str | None = None  # "inbound" | "outbound" | None (both)
    bucket: str = "day"  # "hour" | "day" | "week" — for calls_over_time
    # The organization's real Organization.timezone (IANA name) — bucket
    # boundaries in calls_over_time are computed in this zone so "Today"
    # aligns with the org's actual midnight, not UTC's.
    timezone: str = "UTC"


def _where_and_params(filters: AnalyticsFilters) -> tuple[str, dict]:
    clauses = [
        "c.organization_id = :org_id",
        "c.started_at >= :start_date",
        "c.started_at < :end_date",
    ]
    params: dict = {
        "org_id": filters.organization_id,
        "start_date": filters.start_date,
        "end_date": filters.end_date,
    }
    if filters.agent_id:
        clauses.append("c.voice_agent_id = :agent_id")
        params["agent_id"] = filters.agent_id
    if filters.direction:
        clauses.append("c.direction = :direction")
        params["direction"] = filters.direction
    return " AND ".join(clauses), params


def _base_cte(filters: AnalyticsFilters) -> tuple[str, dict]:
    """The shared per-call derived-stats CTE every query below builds on.

    customer_turn_count / has_customer_turn are computed from the real,
    persisted Transcript.turns JSON — not estimated, not fabricated.
    """
    where_sql, params = _where_and_params(filters)
    cte = f"""
    WITH call_stats AS (
        SELECT
            c.id AS call_id,
            c.started_at,
            c.ended_at,
            c.status,
            c.duration_seconds,
            c.end_reason,
            c.voice_agent_id,
            c.caller_number,
            c.direction,
            c.intent,
            c.outcome,
            COALESCE((
                SELECT COUNT(*)
                FROM jsonb_array_elements(COALESCE(t.turns::jsonb, '[]'::jsonb)) AS elem
                WHERE elem->>'speaker' = 'customer'
            ), 0) AS customer_turn_count
        FROM calls c
        LEFT JOIN transcripts t ON t.call_id = c.id
        WHERE {where_sql}
    )
    """
    return cte, params


# Engaged/human-answered thresholds — documented here once, surfaced to the
# frontend via the API's help-text fields so nothing is a hidden rule.
MIN_ENGAGED_DURATION_SECONDS = 30
MIN_ENGAGED_CUSTOMER_TURNS = 2


class VoiceAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_funnel(self, filters: AnalyticsFilters) -> dict:
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            COUNT(*) AS attempted,
            COUNT(*) AS dialled,
            COUNT(*) FILTER (WHERE status != 'failed') AS connected,
            COUNT(*) FILTER (
                WHERE status != 'failed' AND customer_turn_count >= 1
            ) AS human_answered,
            COUNT(*) FILTER (
                WHERE status != 'failed'
                AND customer_turn_count >= :min_engaged_turns
                AND duration_seconds >= :min_engaged_seconds
            ) AS engaged
        FROM call_stats
        """
        params = {
            **params,
            "min_engaged_turns": MIN_ENGAGED_CUSTOMER_TURNS,
            "min_engaged_seconds": MIN_ENGAGED_DURATION_SECONDS,
        }
        result = await self.session.execute(text(sql), params)
        return dict(result.mappings().one())

    async def get_calls_over_time(self, filters: AnalyticsFilters) -> list[dict]:
        cte, params = _base_cte(filters)
        bucket = filters.bucket if filters.bucket in ("hour", "day", "week") else "day"
        params["tz"] = filters.timezone
        sql = f"""
        {cte}
        SELECT
            date_trunc('{bucket}', started_at AT TIME ZONE :tz) AS bucket_start,
            COUNT(*) AS attempted,
            COUNT(*) AS dialled,
            COUNT(*) FILTER (WHERE status != 'failed') AS connected,
            COUNT(*) FILTER (
                WHERE status != 'failed' AND customer_turn_count >= 1
            ) AS human_answered,
            COUNT(*) FILTER (
                WHERE status != 'failed'
                AND customer_turn_count >= :min_engaged_turns
                AND duration_seconds >= :min_engaged_seconds
            ) AS engaged
        FROM call_stats
        GROUP BY bucket_start
        ORDER BY bucket_start
        """
        params = {
            **params,
            "min_engaged_turns": MIN_ENGAGED_CUSTOMER_TURNS,
            "min_engaged_seconds": MIN_ENGAGED_DURATION_SECONDS,
        }
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_disposition(self, filters: AnalyticsFilters) -> list[dict]:
        """Every attempt, collapsed: connected calls become one "Connected"
        row; unconnected calls are grouped by their real end_reason
        (NULL -> "unknown", never invented)."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            CASE
                WHEN status != 'failed' THEN 'connected'
                ELSE COALESCE(end_reason, 'unknown')
            END AS reason,
            COUNT(*) AS calls
        FROM call_stats
        GROUP BY reason
        ORDER BY calls DESC
        """
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_how_calls_ended(self, filters: AnalyticsFilters) -> list[dict]:
        """Only connected calls, grouped by real end_reason."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT COALESCE(end_reason, 'unknown') AS reason, COUNT(*) AS calls
        FROM call_stats
        WHERE status != 'failed'
        GROUP BY reason
        ORDER BY calls DESC
        """
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_call_duration_stats(self, filters: AnalyticsFilters) -> dict:
        """Real percentile_cont over Postgres — never estimated from
        averages. Scoped to human-answered calls (status != failed and at
        least one real customer turn), matching "human-answered calls"."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            COUNT(*) AS human_answered_calls,
            COALESCE(AVG(duration_seconds), 0) AS average_seconds,
            COALESCE(
                percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds), 0
            ) AS median_seconds,
            COALESCE(
                percentile_cont(0.9) WITHIN GROUP (ORDER BY duration_seconds), 0
            ) AS p90_seconds,
            COALESCE(MAX(duration_seconds), 0) AS longest_seconds
        FROM call_stats
        WHERE status != 'failed' AND customer_turn_count >= 1
        """
        result = await self.session.execute(text(sql), params)
        return dict(result.mappings().one())

    async def get_duration_by_state(self, filters: AnalyticsFilters) -> list[dict]:
        """ "Connected" and "human answered" share duration_seconds since no
        sub-state transition timestamps are persisted yet (see Call model —
        only started_at/ended_at exist). "No response" (connected but the
        customer never said anything) IS derivable from real transcript
        data. True intra-call state timing cannot be reconstructed from
        current data and is intentionally not fabricated here — the service
        layer marks it "not enough data" rather than estimating it."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte},
        connected AS (SELECT * FROM call_stats WHERE status != 'failed')
        SELECT
            'connected' AS state,
            COUNT(*) AS calls,
            COALESCE(AVG(duration_seconds), 0) AS avg_seconds,
            COALESCE(SUM(duration_seconds), 0) AS total_seconds
        FROM connected
        UNION ALL
        SELECT
            'human_answered',
            COUNT(*),
            COALESCE(AVG(duration_seconds), 0),
            COALESCE(SUM(duration_seconds), 0)
        FROM connected WHERE customer_turn_count >= 1
        UNION ALL
        SELECT
            'no_response',
            COUNT(*),
            COALESCE(AVG(duration_seconds), 0),
            COALESCE(SUM(duration_seconds), 0)
        FROM connected WHERE customer_turn_count = 0
        """
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_voicemail_stats(self, filters: AnalyticsFilters) -> dict:
        """No answering-machine detection exists in the runtime today (see
        Call.end_reason's docstring) — this will always be zero until that
        real detection is implemented; it is never estimated."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            COUNT(*) FILTER (WHERE end_reason = 'voicemail') AS voicemail_calls,
            COALESCE(
                SUM(duration_seconds) FILTER (WHERE end_reason = 'voicemail'), 0
            ) AS duration_seconds
        FROM call_stats
        """
        result = await self.session.execute(text(sql), params)
        return dict(result.mappings().one())

    async def get_outcomes(self, filters: AnalyticsFilters) -> list[dict]:
        """Real Call.outcome, populated by the real post-call LLM analysis
        pipeline (run_call_analysis_pipeline) — not derived here."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT COALESCE(outcome, 'none') AS outcome, COUNT(*) AS calls,
               COALESCE(AVG(duration_seconds), 0) AS avg_talk_time_seconds
        FROM call_stats
        WHERE status != 'failed' AND customer_turn_count >= 1
        GROUP BY outcome
        ORDER BY calls DESC
        """
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_intent_distribution(self, filters: AnalyticsFilters) -> list[dict]:
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT intent, COUNT(*) AS calls
        FROM call_stats
        WHERE intent IS NOT NULL
        GROUP BY intent
        ORDER BY calls DESC
        """
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_by_caller_number(self, filters: AnalyticsFilters) -> list[dict]:
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            COALESCE(caller_number, 'unknown') AS number,
            COUNT(*) AS attempted,
            COUNT(*) FILTER (WHERE status != 'failed') AS connected,
            COALESCE(
                AVG(duration_seconds) FILTER (WHERE status != 'failed'), 0
            ) AS avg_duration_seconds
        FROM call_stats
        GROUP BY number
        ORDER BY attempted DESC
        """
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_by_agent(self, filters: AnalyticsFilters) -> list[dict]:
        """Real Call.voice_agent_id joined to VoiceAgent for the real name
        — resolved at the SQL layer, never picked from an unrelated index
        on the frontend."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            cs.voice_agent_id AS agent_id,
            va.name AS agent_name,
            COUNT(*) AS attempted,
            COUNT(*) FILTER (
                WHERE cs.status != 'failed' AND cs.customer_turn_count >= 1
            ) AS human_answered,
            COUNT(*) FILTER (
                WHERE cs.status != 'failed'
                AND cs.customer_turn_count >= :min_engaged_turns
                AND cs.duration_seconds >= :min_engaged_seconds
            ) AS engaged,
            COALESCE(
                AVG(cs.duration_seconds) FILTER (WHERE cs.status != 'failed'), 0
            ) AS avg_duration_seconds
        FROM call_stats cs
        JOIN voice_agents va ON va.id = cs.voice_agent_id
        GROUP BY cs.voice_agent_id, va.name
        ORDER BY attempted DESC
        """
        params = {
            **params,
            "min_engaged_turns": MIN_ENGAGED_CUSTOMER_TURNS,
            "min_engaged_seconds": MIN_ENGAGED_DURATION_SECONDS,
        }
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]

    async def get_connect_rate_by_attempt(self, filters: AnalyticsFilters) -> list[dict]:
        """Jaan has no multi-attempt/retry dialer yet (see plan notes) —
        every call is attempt #1. Structured as a list so the frontend
        chart and the response shape are ready for real retry data the
        moment a campaign/retry system exists, without a contract change."""
        cte, params = _base_cte(filters)
        sql = f"""
        {cte}
        SELECT
            1 AS attempt_number,
            COUNT(*) AS dialled,
            COUNT(*) FILTER (WHERE status != 'failed') AS connected
        FROM call_stats
        """
        result = await self.session.execute(text(sql), params)
        row = dict(result.mappings().one())
        return [row] if row["dialled"] else []
