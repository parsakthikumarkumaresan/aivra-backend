from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.api.dependencies import require_voice_role
from app.ai_employees.voice.repositories.call_repository import CallRepository
from app.ai_employees.voice.schemas.analytics import VoiceAnalyticsResponse
from app.shared.database.session import get_db
from app.shared.rbac.roles import OrgRole
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/analytics/voice", tags=["Voice Analytics"])


@router.get("", response_model=VoiceAnalyticsResponse)
async def get_voice_analytics(
    auth: AuthContext = Depends(
        require_voice_role(
            OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> VoiceAnalyticsResponse:
    org_id = auth.require_organization_id()
    call_repo = CallRepository(db)
    calls = await call_repo.list_for_organization(org_id)

    total_calls = len(calls)
    if total_calls == 0:
        return VoiceAnalyticsResponse(
            total_calls=0,
            resolution_rate=0.0,
            average_duration_seconds=0.0,
            escalation_rate=0.0,
            intent_breakdown={},
            outcome_breakdown={},
        )

    resolved_count = 0
    escalated_count = 0
    total_duration = 0
    intent_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}

    for call in calls:
        total_duration += call.duration_seconds
        if call.escalated:
            escalated_count += 1
        if call.outcome:
            out_val = call.outcome.value
            outcome_counts[out_val] = outcome_counts.get(out_val, 0) + 1
            if out_val in ("resolved", "booked"):
                resolved_count += 1
        if call.intent:
            intent_val = call.intent.value
            intent_counts[intent_val] = intent_counts.get(intent_val, 0) + 1

    return VoiceAnalyticsResponse(
        total_calls=total_calls,
        resolution_rate=round(resolved_count / total_calls, 4),
        average_duration_seconds=round(total_duration / total_calls, 2),
        escalation_rate=round(escalated_count / total_calls, 4),
        intent_breakdown=intent_counts,
        outcome_breakdown=outcome_counts,
    )
