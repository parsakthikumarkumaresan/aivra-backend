from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models.lead import Lead, LeadStatus


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

    async def search_and_count(
        self,
        *,
        query: str | None,
        status: LeadStatus | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Lead], int]:
        """Admin Leads directory (Phase 6) — same offset-pagination shape
        established for the Customer Directory in Phase 5
        (app.organizations.repositories.OrganizationRepository.search_and_count).
        """
        filters = []
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(
                or_(
                    Lead.company_name.ilike(pattern),
                    Lead.contact_name.ilike(pattern),
                    Lead.contact_email.ilike(pattern),
                )
            )
        if status is not None:
            filters.append(Lead.status == status)

        count_stmt = select(func.count()).select_from(Lead)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = select(Lead).order_by(Lead.created_at.desc())
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total
