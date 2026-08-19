from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class PhoneNumberStatus(StrEnum):
    ACTIVE = "active"
    UNASSIGNED = "unassigned"
    PORTING = "porting"


class PhoneNumber(Base, OrgScopedMixin):
    __tablename__ = "phone_numbers"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.PHONE_NUMBER)
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("telephony_provider_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[PhoneNumberStatus] = mapped_column(
        str_enum_column(PhoneNumberStatus, 20), default=PhoneNumberStatus.UNASSIGNED, nullable=False
    )
    monthly_cost: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
