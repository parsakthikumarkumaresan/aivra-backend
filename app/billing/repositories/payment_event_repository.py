from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models.payment_event import PaymentEvent


class PaymentEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_provider_event_id(self, provider_event_id: str) -> PaymentEvent | None:
        stmt = select(PaymentEvent).where(PaymentEvent.provider_event_id == provider_event_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def record(
        self,
        *,
        organization_id: str,
        provider: str,
        provider_event_id: str,
        event_type: str,
        payload: str,
    ) -> PaymentEvent:
        event = PaymentEvent(
            organization_id=organization_id,
            provider=provider,
            provider_event_id=provider_event_id,
            event_type=event_type,
            payload=payload,
            processed_at=datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()
        return event
