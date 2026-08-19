from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.tool_execution import ToolExecution
from app.shared.database.repository import OrgScopedRepository


class ToolExecutionRepository(OrgScopedRepository[ToolExecution]):
    model = ToolExecution

    async def list_for_call(self, organization_id: str, call_id: str) -> list[ToolExecution]:
        stmt = (
            select(ToolExecution)
            .where(
                ToolExecution.organization_id == organization_id,
                ToolExecution.call_id == call_id,
            )
            .order_by(ToolExecution.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
