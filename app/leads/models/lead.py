from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


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


# Phase 6 sales-triage lifecycle — separate from VoiceProject's own
# implementation lifecycle (VOICE_PROJECT_TRANSITIONS in
# app.leads.models.voice_project). CONVERTED is intentionally NOT reachable
# through this generic table: converting a lead also requires attaching a
# real organization_id, which only POST /leads/{id}/convert does — see
# LeadService.convert_lead, unchanged by this state machine.
LEAD_TRANSITIONS = StateMachine[LeadStatus](
    {
        LeadStatus.NEW: frozenset({LeadStatus.CONTACTED, LeadStatus.REJECTED}),
        LeadStatus.CONTACTED: frozenset({LeadStatus.QUALIFIED, LeadStatus.REJECTED}),
        LeadStatus.QUALIFIED: frozenset({LeadStatus.REJECTED}),
        LeadStatus.CONVERTED: frozenset(),
        LeadStatus.REJECTED: frozenset(),
    }
)


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
