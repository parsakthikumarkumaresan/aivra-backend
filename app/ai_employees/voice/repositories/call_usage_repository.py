from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.call_usage import CallUsage
from app.shared.database.repository import OrgScopedRepository


class CallUsageRepository(OrgScopedRepository[CallUsage]):
    model = CallUsage

    async def get_by_call_id(self, organization_id: str, call_id: str) -> CallUsage | None:
        stmt = select(CallUsage).where(
            CallUsage.organization_id == organization_id,
            CallUsage.call_id == call_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
