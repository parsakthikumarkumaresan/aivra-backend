from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.interview_panelist import InterviewPanelist
from app.shared.database.repository import OrgScopedRepository


class InterviewPanelistRepository(OrgScopedRepository[InterviewPanelist]):
    model = InterviewPanelist

    async def list_for_interview(
        self, organization_id: str, interview_id: str
    ) -> list[InterviewPanelist]:
        stmt = select(InterviewPanelist).where(
            InterviewPanelist.organization_id == organization_id,
            InterviewPanelist.interview_id == interview_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
