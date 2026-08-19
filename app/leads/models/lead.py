from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class LeadType(StrEnum):
    """Spec section 16."""

    DEMO_REQUEST = "demo_request"
    VOICE_CUSTOMIZATION = "voice_customization"
    HR_SALES_REQUEST = "hr_sales_request"


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    REJECTED = "rejected"


class Lead(Base, TimestampMixin):
    """A public-facing demo/customization/sales inquiry.

    Not org-scoped (``OrgScopedMixin``): a lead usually arrives before any
    AIVRA account exists. ``organization_id`` is populated only once the
    lead converts into a real customer organization.
    """

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.LEAD)
    )
    type: Mapped[LeadType] = mapped_column(str_enum_column(LeadType, 30), nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        str_enum_column(LeadStatus, 20), default=LeadStatus.NEW, nullable=False
    )
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(Text)
    organization_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
