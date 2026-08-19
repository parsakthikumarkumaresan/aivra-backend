from __future__ import annotations

from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class TelephonyProviderType(StrEnum):
    """Spec section 14/29."""

    TWILIO = "twilio"
    PLIVO = "plivo"
    EXOTEL = "exotel"
    TATA_TELE = "tata_tele"
    SIP_BYOC = "sip_byoc"


class TelephonyAccountStatus(StrEnum):
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"


class TelephonyProviderAccount(Base, OrgScopedMixin):
    """A connected telephony provider account (spec section 14). Holds only
    a reference to the credential, never the raw secret (spec section 23).
    """

    __tablename__ = "telephony_provider_accounts"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.TELEPHONY_PROVIDER)
    )
    provider_type: Mapped[TelephonyProviderType] = mapped_column(
        str_enum_column(TelephonyProviderType, 20), nullable=False
    )
    account_label: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[TelephonyAccountStatus] = mapped_column(
        str_enum_column(TelephonyAccountStatus, 20),
        default=TelephonyAccountStatus.NOT_CONNECTED,
        nullable=False,
    )
    credential_ref: Mapped[str | None] = mapped_column(String(255))
