from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.schedule_slot import ScheduleSlot
from app.shared.database.repository import OrgScopedRepository


class ScheduleSlotRepository(OrgScopedRepository[ScheduleSlot]):
    model = ScheduleSlot

    async def list_available(self, organization_id: str) -> list[ScheduleSlot]:
        stmt = (
            select(ScheduleSlot)
            .where(
                ScheduleSlot.organization_id == organization_id,
                ScheduleSlot.is_booked.is_(False),
            )
            .order_by(ScheduleSlot.start_time.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
