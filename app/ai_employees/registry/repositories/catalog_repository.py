from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.registry.models.catalog import AIEmployeeType, EmployeeCatalogItem


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_employee_types(self) -> list[AIEmployeeType]:
        stmt = select(AIEmployeeType).where(AIEmployeeType.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_employee_type(self, employee_type_id: str) -> AIEmployeeType | None:
        return await self.session.get(AIEmployeeType, employee_type_id)

    async def get_employee_type_by_code(self, code: str) -> AIEmployeeType | None:
        stmt = select(AIEmployeeType).where(AIEmployeeType.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_catalog_item_for_type(self, employee_type_id: str) -> EmployeeCatalogItem | None:
        stmt = select(EmployeeCatalogItem).where(
            EmployeeCatalogItem.employee_type_id == employee_type_id,
            EmployeeCatalogItem.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
