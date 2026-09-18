from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.shared.database.base import Base, OrgScopedMixin, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class QuoteStatus(StrEnum):
    """Lifecycle stages for JEXA Admin quotes."""

    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class QuoteLineItemCategory(StrEnum):
    """Commercial categories for quote breakdown."""

    IMPLEMENTATION = "implementation"
    PLATFORM = "platform"
    VOICE_CREDITS = "voice_credits"
    INTEGRATIONS = "integrations"
    DEVELOPMENT = "development"
    OTHER = "other"


QUOTE_TRANSITIONS = StateMachine[QuoteStatus](
    {
        QuoteStatus.DRAFT: frozenset({QuoteStatus.SENT, QuoteStatus.REJECTED}),
        QuoteStatus.SENT: frozenset(
            {QuoteStatus.ACCEPTED, QuoteStatus.REJECTED, QuoteStatus.EXPIRED}
        ),
        QuoteStatus.ACCEPTED: frozenset(),
        QuoteStatus.REJECTED: frozenset(),
        QuoteStatus.EXPIRED: frozenset(),
    }
)


class Quote(Base, OrgScopedMixin):
    """An internal JEXA Admin quotation proposal (Phase 7).

    Snapshots the commercial agreements (fees, rates, included credits,
    line items) so historical quotes never dynamically fluctuate when
    pricing formulas or catalog rates change.
    """

    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.QUOTE)
    )
    lead_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    voice_project_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("voice_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quote_number: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[QuoteStatus] = mapped_column(
        str_enum_column(QuoteStatus, 20), default=QuoteStatus.DRAFT, nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    # Commercial values (Decimal with 2 decimal precision)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    discount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)

    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)

    # Internal estimate reference values
    estimated_setup_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estimated_recurring_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    included_voice_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    additional_minute_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    calculation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )

    created_by_user_id: Mapped[str | None] = mapped_column(String(40))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    line_items: Mapped[list[QuoteLineItem]] = relationship(
        "QuoteLineItem",
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteLineItem.display_order",
        lazy="selectin",
    )


class QuoteLineItem(Base, TimestampMixin):
    """An individual line item within a Quote snapshot."""

    __tablename__ = "quote_line_items"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.QUOTE_LINE_ITEM)
    )
    quote_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[QuoteLineItemCategory] = mapped_column(
        str_enum_column(QuoteLineItemCategory, 30), nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("1.00"), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(50), default="one-time", nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    quote: Mapped[Quote] = relationship("Quote", back_populates="line_items")
