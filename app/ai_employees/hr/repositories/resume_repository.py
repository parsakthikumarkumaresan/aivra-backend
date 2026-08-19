from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.resume import Resume
from app.shared.database.repository import OrgScopedRepository


class ResumeRepository(OrgScopedRepository[Resume]):
    model = Resume

    async def get_for_candidate(self, organization_id: str, candidate_id: str) -> Resume | None:
        stmt = select(Resume).where(
            Resume.organization_id == organization_id, Resume.candidate_id == candidate_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
