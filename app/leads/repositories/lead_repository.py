from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models.lead import Lead


class LeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, lead: Lead) -> Lead:
        self.session.add(lead)
        await self.session.flush()
        return lead

    async def get_by_id(self, lead_id: str) -> Lead | None:
        return await self.session.get(Lead, lead_id)

    async def list_all(self) -> list[Lead]:
        stmt = select(Lead).order_by(Lead.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
