from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.api.dependencies import require_voice_role
from app.ai_employees.voice.repositories.analytics_repository import VoiceAnalyticsRepository
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.schemas.analytics import VoiceAnalyticsResponse
from app.ai_employees.voice.services.voice_analytics_service import VoiceAnalyticsService
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import OrgRole
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/analytics/voice", tags=["Voice Analytics"])


@router.get("", response_model=VoiceAnalyticsResponse)
async def get_voice_analytics(
    date_range: str = Query("today", alias="dateRange"),
    agent_id: str | None = Query(None, alias="agentId"),
    direction: str | None = Query(None),
    start_date: datetime | None = Query(None, alias="startDate"),
    end_date: datetime | None = Query(None, alias="endDate"),
    auth: AuthContext = Depends(
        require_voice_role(
            OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> VoiceAnalyticsResponse:
    """Real, SQL-aggregated Jaan call analytics for the caller's own
    organization (agent_id, if supplied, is validated against that same
    organization server-side — never trusted blindly from the client). See
    app.ai_employees.voice.services.voice_analytics_service for how every
    section is computed.
    """
    org_id = auth.require_organization_id()
    org = await OrganizationRepository(db).get_by_id(org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    service = VoiceAnalyticsService(
        VoiceAnalyticsRepository(db),
        VoiceAgentRepository(db),
    )
    return await service.get_analytics(
        organization_id=org_id,
        organization_timezone=org.timezone,
        date_range=date_range,
        agent_id=agent_id,
        direction=direction,
        start_date=start_date,
        end_date=end_date,
    )
