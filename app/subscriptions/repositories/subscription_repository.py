from __future__ import annotations

from sqlalchemy import select

from app.shared.database.repository import OrgScopedRepository
from app.subscriptions.models.subscription import Subscription


class SubscriptionRepository(OrgScopedRepository[Subscription]):
    model = Subscription

    async def get_for_employee_type(
        self, organization_id: str, employee_type_id: str
    ) -> Subscription | None:
        stmt = select(Subscription).where(
            Subscription.organization_id == organization_id,
            Subscription.employee_type_id == employee_type_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider_subscription_id(
        self, provider_subscription_id: str
    ) -> Subscription | None:
        stmt = select(Subscription).where(
            Subscription.provider_subscription_id == provider_subscription_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: str) -> list[Subscription]:
        stmt = select(Subscription).where(Subscription.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
