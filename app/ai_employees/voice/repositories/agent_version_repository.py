from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.agent_version import AgentVersion, AgentVersionStatus
from app.shared.database.repository import OrgScopedRepository


class AgentVersionRepository(OrgScopedRepository[AgentVersion]):
    model = AgentVersion

    async def get_draft(self, organization_id: str, voice_agent_id: str) -> AgentVersion | None:
        stmt = select(AgentVersion).where(
            AgentVersion.organization_id == organization_id,
            AgentVersion.voice_agent_id == voice_agent_id,
            AgentVersion.status == AgentVersionStatus.DRAFT,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active_published(
        self, organization_id: str, voice_agent_id: str
    ) -> AgentVersion | None:
        stmt = select(AgentVersion).where(
            AgentVersion.organization_id == organization_id,
            AgentVersion.voice_agent_id == voice_agent_id,
            AgentVersion.status == AgentVersionStatus.PUBLISHED,
            AgentVersion.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_latest_version_number(
        self, organization_id: str, voice_agent_id: str
    ) -> int:
        stmt = (
            select(AgentVersion.version_number)
            .where(
                AgentVersion.organization_id == organization_id,
                AgentVersion.voice_agent_id == voice_agent_id,
            )
            .order_by(AgentVersion.version_number.desc())
        )
        result = await self.session.execute(stmt)
        latest = result.scalars().first()
        return latest or 0

    async def list_for_agent(self, organization_id: str, voice_agent_id: str) -> list[AgentVersion]:
        stmt = (
            select(AgentVersion)
            .where(
                AgentVersion.organization_id == organization_id,
                AgentVersion.voice_agent_id == voice_agent_id,
            )
            .order_by(AgentVersion.version_number.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
