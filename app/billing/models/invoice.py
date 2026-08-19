from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


class Invoice(Base, OrgScopedMixin):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.INVOICE)
    )
    subscription_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        str_enum_column(InvoiceStatus, 20), default=InvoiceStatus.OPEN, nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_invoice_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    hosted_invoice_url: Mapped[str | None] = mapped_column(String(500))
