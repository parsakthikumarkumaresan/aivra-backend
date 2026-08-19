from __future__ import annotations

from sqlalchemy import select

from app.billing.models.invoice import Invoice
from app.shared.database.repository import OrgScopedRepository


class InvoiceRepository(OrgScopedRepository[Invoice]):
    model = Invoice

    async def list_for_organization(self, organization_id: str) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .where(Invoice.organization_id == organization_id)
            .order_by(Invoice.period_start.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_provider_invoice_id(self, provider_invoice_id: str) -> Invoice | None:
        stmt = select(Invoice).where(Invoice.provider_invoice_id == provider_invoice_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
