from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.tool import Tool
from app.shared.database.repository import OrgScopedRepository


class ToolRepository(OrgScopedRepository[Tool]):
    model = Tool

    async def list_for_organization(self, organization_id: str) -> list[Tool]:
        stmt = select(Tool).where(Tool.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ids(self, organization_id: str, tool_ids: list[str]) -> list[Tool]:
        if not tool_ids:
            return []
        stmt = select(Tool).where(
            Tool.organization_id == organization_id,
            Tool.id.in_(tool_ids),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
