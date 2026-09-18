from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class RechargeOrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class RechargeOrder(Base, OrgScopedMixin):
    """A customer's purchase of a Jaan Voice Credit package (spec section
    2). ``minutes``/``amount``/``currency`` are snapshotted from the
    RechargePackage at order-creation time — deliberately not a live FK
    read, so a later price/package change never rewrites a past order's
    financial record.

    Reaching PAID creates exactly one RECHARGE CreditTransaction
    (RechargeService.handle_stripe_webhook) — never on this row's own
    status flip; the status flip and the ledger transaction happen in the
    same DB transaction so they can never disagree.
    """

    __tablename__ = "voice_recharge_orders"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.RECHARGE_ORDER)
    )
    package_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("voice_recharge_packages.id", ondelete="SET NULL")
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[RechargeOrderStatus] = mapped_column(
        str_enum_column(RechargeOrderStatus, 20),
        default=RechargeOrderStatus.PENDING,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(30), default="stripe", nullable=False)
    provider_checkout_session_id: Mapped[str | None] = mapped_column(String(160), index=True)
    provider_payment_reference: Mapped[str | None] = mapped_column(String(160))
    created_by_user_id: Mapped[str | None] = mapped_column(String(40))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
