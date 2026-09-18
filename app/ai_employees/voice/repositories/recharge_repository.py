from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.recharge_order import RechargeOrder
from app.ai_employees.voice.models.recharge_package import RechargePackage
from app.shared.database.repository import OrgScopedRepository


class RechargeOrderRepository(OrgScopedRepository[RechargeOrder]):
    model = RechargeOrder

    async def list_for_organization(
        self, organization_id: str, *, limit: int = 50
    ) -> list[RechargeOrder]:
        result = await self.session.execute(
            select(RechargeOrder)
            .where(RechargeOrder.organization_id == organization_id)
            .order_by(RechargeOrder.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_checkout_session_id(
        self, provider_checkout_session_id: str
    ) -> RechargeOrder | None:
        result = await self.session.execute(
            select(RechargeOrder).where(
                RechargeOrder.provider_checkout_session_id == provider_checkout_session_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_checkout_session_id_for_update(
        self, provider_checkout_session_id: str
    ) -> RechargeOrder | None:
        """Row-level lock for the webhook handler: this row already exists
        by the time Stripe calls back, so (unlike the ledger balance) a
        plain ``FOR UPDATE`` is sufficient — it serializes against any
        concurrent delivery of the same/an overlapping webhook event for
        this exact order.
        """
        result = await self.session.execute(
            select(RechargeOrder)
            .where(RechargeOrder.provider_checkout_session_id == provider_checkout_session_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()


class RechargePackageRepository:
    """Not org-scoped — a global, admin-managed catalog (see RechargePackage)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[RechargePackage]:
        result = await self.session.execute(
            select(RechargePackage)
            .where(RechargePackage.is_active.is_(True))
            .order_by(RechargePackage.display_order, RechargePackage.minutes)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[RechargePackage]:
        result = await self.session.execute(
            select(RechargePackage).order_by(RechargePackage.display_order, RechargePackage.minutes)
        )
        return list(result.scalars().all())

    async def get_by_id(self, package_id: str) -> RechargePackage | None:
        result = await self.session.execute(
            select(RechargePackage).where(RechargePackage.id == package_id)
        )
        return result.scalar_one_or_none()

    async def add(self, package: RechargePackage) -> RechargePackage:
        self.session.add(package)
        await self.session.flush()
        return package
