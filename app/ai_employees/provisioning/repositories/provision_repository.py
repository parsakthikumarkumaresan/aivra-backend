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

    async def add_event(self, event: ProvisioningEvent) -> ProvisioningEvent:
        self.session.add(event)
        await self.session.flush()
        return event
