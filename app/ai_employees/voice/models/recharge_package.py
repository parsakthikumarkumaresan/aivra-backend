from __future__ import annotations

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id


class RechargePackage(Base, TimestampMixin):
    """Admin-configurable Jaan Voice Credit recharge catalog (spec section
    3). Deliberately NOT org-scoped — this is a global commercial catalog
    AIVRA manages (like Plan for subscriptions), not a per-tenant record.
    Pricing must come from here, never be hardcoded in the frontend.
    """

    __tablename__ = "voice_recharge_packages"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.RECHARGE_PACKAGE)
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
