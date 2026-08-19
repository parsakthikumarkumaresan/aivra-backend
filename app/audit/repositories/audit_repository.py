from __future__ import annotations

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from app.shared.database.repository import OrgScopedRepository


class AuditRepository(OrgScopedRepository[AuditEvent]):
    model = AuditEvent

    async def list_for_organization(
        self, organization_id: str, *, resource_type: str | None = None
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent).where(AuditEvent.organization_id == organization_id)
        if resource_type is not None:
            stmt = stmt.where(AuditEvent.resource_type == resource_type)
        stmt = stmt.order_by(AuditEvent.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
