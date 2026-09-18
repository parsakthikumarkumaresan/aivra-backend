from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.provisioning.models.provision import EmployeeProvision, ProvisioningEvent
from app.shared.database.repository import OrgScopedRepository


class ProvisionRepository(OrgScopedRepository[EmployeeProvision]):
    model = EmployeeProvision

    async def get_for_employee_type(
        self, organization_id: str, employee_type_id: str
    ) -> EmployeeProvision | None:
        stmt = select(EmployeeProvision).where(
            EmployeeProvision.organization_id == organization_id,
            EmployeeProvision.employee_type_id == employee_type_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: str) -> list[EmployeeProvision]:
        stmt = select(EmployeeProvision).where(EmployeeProvision.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_organizations(self, organization_ids: list[str]) -> list[EmployeeProvision]:
        """Batched lookup for the admin Customer Directory (Phase 5) — one
        query for a whole page of organizations, not one per row.
        """
        if not organization_ids:
            return []
        stmt = select(EmployeeProvision).where(
            EmployeeProvision.organization_id.in_(organization_ids)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_event(self, event: ProvisioningEvent) -> ProvisioningEvent:
        self.session.add(event)
        await self.session.flush()
        return event
