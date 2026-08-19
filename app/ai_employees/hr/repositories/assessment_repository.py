from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.assessment import Assessment
from app.shared.database.repository import OrgScopedRepository


class AssessmentRepository(OrgScopedRepository[Assessment]):
    model = Assessment

    async def get_latest_for_candidate(
        self, organization_id: str, candidate_id: str
    ) -> Assessment | None:
        stmt = (
            select(Assessment)
            .where(
                Assessment.organization_id == organization_id,
                Assessment.candidate_id == candidate_id,
            )
            .order_by(Assessment.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
