from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class SipTrunkStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SipTrunk(Base, OrgScopedMixin):
    """SIP/BYOC trunk configuration (spec section 14)."""

    __tablename__ = "sip_trunks"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.SIP_TRUNK)
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("telephony_provider_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SipTrunkStatus] = mapped_column(
        str_enum_column(SipTrunkStatus, 20), default=SipTrunkStatus.ACTIVE, nullable=False
    )
    codec: Mapped[str] = mapped_column(String(20), default="OPUS", nullable=False)
