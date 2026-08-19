from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class BillingCycle(StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class Plan(Base, TimestampMixin):
    """A purchasable plan for a self-service AI Employee (HR)."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.PLAN)
    )
    employee_type_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("ai_employee_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    billing_cycle: Mapped[BillingCycle] = mapped_column(
        str_enum_column(BillingCycle, 20), nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    # Provider-side price identifier (e.g. Stripe Price ID) — opaque to domain logic.
    external_price_id: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
