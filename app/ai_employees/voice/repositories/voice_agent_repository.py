from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.voice_agent import VoiceAgent
from app.shared.database.repository import OrgScopedRepository


class VoiceAgentRepository(OrgScopedRepository[VoiceAgent]):
    model = VoiceAgent

    async def list_for_organization(self, organization_id: str) -> list[VoiceAgent]:
        stmt = select(VoiceAgent).where(VoiceAgent.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
