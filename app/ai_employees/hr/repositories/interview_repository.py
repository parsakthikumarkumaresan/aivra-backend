from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.interview import Interview
from app.shared.database.repository import OrgScopedRepository


class InterviewRepository(OrgScopedRepository[Interview]):
    model = Interview

    async def get_for_candidate(self, organization_id: str, candidate_id: str) -> Interview | None:
        stmt = (
            select(Interview)
            .where(
                Interview.organization_id == organization_id,
                Interview.candidate_id == candidate_id,
            )
            .order_by(Interview.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_all(self, organization_id: str) -> list[Interview]:
        stmt = select(Interview).where(Interview.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
