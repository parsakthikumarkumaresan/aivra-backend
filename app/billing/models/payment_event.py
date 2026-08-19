from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id


class PaymentEvent(Base, OrgScopedMixin):
    """Raw webhook event ledger — the idempotency guard for payment webhooks
    (spec sections 23, 28, 39: duplicate webhook idempotency is a mandatory
    test). ``provider_event_id`` is globally unique so the same event can
    never be applied twice even under provider retries.
    """

    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.PAYMENT_EVENT)
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
