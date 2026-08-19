from __future__ import annotations

from sqlalchemy import select

from app.knowledge.models.source_version import SourceVersion
from app.shared.database.repository import OrgScopedRepository


class SourceVersionRepository(OrgScopedRepository[SourceVersion]):
    model = SourceVersion

    async def get_latest_for_source(
        self, organization_id: str, knowledge_source_id: str
    ) -> SourceVersion | None:
        stmt = (
            select(SourceVersion)
            .where(
                SourceVersion.organization_id == organization_id,
                SourceVersion.knowledge_source_id == knowledge_source_id,
            )
            .order_by(SourceVersion.version_number.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
