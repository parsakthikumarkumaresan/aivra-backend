from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.subscriptions.models.plan import Plan


class PlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_employee_type(self, employee_type_id: str) -> list[Plan]:
        stmt = select(Plan).where(
            Plan.employee_type_id == employee_type_id, Plan.is_active.is_(True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, plan_id: str) -> Plan | None:
        return await self.session.get(Plan, plan_id)

    async def get_default_for_employee_type_and_cycle(
        self, employee_type_id: str, billing_cycle: str
    ) -> Plan | None:
        stmt = select(Plan).where(
            Plan.employee_type_id == employee_type_id,
            Plan.billing_cycle == billing_cycle,
            Plan.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
