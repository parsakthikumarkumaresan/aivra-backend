from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine
from app.subscriptions.models.plan import BillingCycle


class SubscriptionStatus(StrEnum):
    """Spec section 43.1."""

    NOT_HIRED = "not_hired"
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    PAUSED = "paused"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


SUBSCRIPTION_TRANSITIONS = StateMachine[SubscriptionStatus](
    {
        SubscriptionStatus.NOT_HIRED: frozenset({SubscriptionStatus.PENDING_ACTIVATION}),
        SubscriptionStatus.PENDING_ACTIVATION: frozenset(
            {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED}
        ),
        SubscriptionStatus.ACTIVE: frozenset(
            {
                SubscriptionStatus.PAUSED,
                SubscriptionStatus.PAST_DUE,
                SubscriptionStatus.CANCELLED,
                SubscriptionStatus.EXPIRED,
            }
        ),
        SubscriptionStatus.PAUSED: frozenset(
            {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED}
        ),
        SubscriptionStatus.PAST_DUE: frozenset(
            {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED}
        ),
        SubscriptionStatus.CANCELLED: frozenset(),
        SubscriptionStatus.EXPIRED: frozenset({SubscriptionStatus.PENDING_ACTIVATION}),
    }
)


class Subscription(Base, OrgScopedMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "employee_type_id", name="uq_subscription_org_employee_type"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.SUBSCRIPTION)
    )
    employee_type_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("ai_employee_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        str_enum_column(SubscriptionStatus, 30),
        default=SubscriptionStatus.NOT_HIRED,
        nullable=False,
    )
    billing_cycle: Mapped[BillingCycle] = mapped_column(
        str_enum_column(BillingCycle, 20), nullable=False
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Stripe (or future provider) identifiers — opaque to domain logic.
    provider_customer_id: Mapped[str | None] = mapped_column(String(120))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(120), index=True)
