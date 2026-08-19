from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.screening import Screening
from app.shared.database.repository import OrgScopedRepository


class ScreeningRepository(OrgScopedRepository[Screening]):
    model = Screening

    async def get_for_candidate(self, organization_id: str, candidate_id: str) -> Screening | None:
        stmt = (
            select(Screening)
            .where(
                Screening.organization_id == organization_id,
                Screening.candidate_id == candidate_id,
            )
            .order_by(Screening.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_all(self, organization_id: str) -> list[Screening]:
        stmt = select(Screening).where(Screening.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
