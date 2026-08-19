from __future__ import annotations

from sqlalchemy import select

from app.knowledge.models.source import KnowledgeSource
from app.shared.database.repository import OrgScopedRepository


class SourceRepository(OrgScopedRepository[KnowledgeSource]):
    model = KnowledgeSource

    async def list_for_organization(self, organization_id: str) -> list[KnowledgeSource]:
        stmt = select(KnowledgeSource).where(KnowledgeSource.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
