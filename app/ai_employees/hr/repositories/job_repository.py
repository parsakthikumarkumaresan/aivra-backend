from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.job import HrJob
from app.shared.database.repository import OrgScopedRepository


class JobRepository(OrgScopedRepository[HrJob]):
    model = HrJob

    async def list_for_organization(self, organization_id: str) -> list[HrJob]:
        stmt = (
            select(HrJob)
            .where(HrJob.organization_id == organization_id)
            .order_by(HrJob.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
