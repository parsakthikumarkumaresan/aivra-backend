from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.call_analysis import CallAnalysis
from app.shared.database.repository import OrgScopedRepository


class CallAnalysisRepository(OrgScopedRepository[CallAnalysis]):
    model = CallAnalysis

    async def get_by_call_id(self, organization_id: str, call_id: str) -> CallAnalysis | None:
        stmt = select(CallAnalysis).where(
            CallAnalysis.organization_id == organization_id,
            CallAnalysis.call_id == call_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_organization(self, organization_id: str) -> list[CallAnalysis]:
        stmt = select(CallAnalysis).where(CallAnalysis.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
