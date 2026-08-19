from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.integration import CalendarIntegration, IntegrationProvider
from app.shared.database.repository import OrgScopedRepository


class IntegrationRepository(OrgScopedRepository[CalendarIntegration]):
    model = CalendarIntegration

    async def get_for_provider(
        self, organization_id: str, provider: IntegrationProvider
    ) -> CalendarIntegration | None:
        stmt = select(CalendarIntegration).where(
            CalendarIntegration.organization_id == organization_id,
            CalendarIntegration.provider == provider,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
