from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class ProvisionStatus(StrEnum):
    """Spec section 8. HR activation is subscription-driven; Voice activation is
    AIVRA customization/deployment-driven — see app.ai_employees.provisioning.services
    for which side is allowed to trigger each transition.
    """

    NOT_PROVISIONED = "not_provisioned"
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    PAUSED = "paused"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DEPLOYMENT_FAILED = "deployment_failed"


PROVISION_TRANSITIONS = StateMachine[ProvisionStatus](
    {
        ProvisionStatus.NOT_PROVISIONED: frozenset(
            {ProvisionStatus.PENDING_ACTIVATION}
        ),
        ProvisionStatus.PENDING_ACTIVATION: frozenset(
            {ProvisionStatus.ACTIVE, ProvisionStatus.DEPLOYMENT_FAILED, ProvisionStatus.CANCELLED}
        ),
        ProvisionStatus.ACTIVE: frozenset(
            {
                ProvisionStatus.PAUSED,
                ProvisionStatus.PAST_DUE,
                ProvisionStatus.CANCELLED,
                ProvisionStatus.EXPIRED,
            }
        ),
        ProvisionStatus.PAUSED: frozenset(
            {ProvisionStatus.ACTIVE, ProvisionStatus.CANCELLED, ProvisionStatus.EXPIRED}
        ),
        ProvisionStatus.PAST_DUE: frozenset(
            {ProvisionStatus.ACTIVE, ProvisionStatus.CANCELLED, ProvisionStatus.EXPIRED}
        ),
        ProvisionStatus.DEPLOYMENT_FAILED: frozenset(
            {ProvisionStatus.PENDING_ACTIVATION, ProvisionStatus.CANCELLED}
        ),
        ProvisionStatus.CANCELLED: frozenset(),
        ProvisionStatus.EXPIRED: frozenset({ProvisionStatus.PENDING_ACTIVATION}),
    }
)


class EmployeeProvision(Base, OrgScopedMixin):
    """An organization's entitlement/instance of one AI Employee type."""

    __tablename__ = "employee_provisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "employee_type_id", name="uq_provision_org_employee_type"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.EMPLOYEE_PROVISION)
    )
    employee_type_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("ai_employee_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[ProvisionStatus] = mapped_column(
        str_enum_column(ProvisionStatus, 30),
        default=ProvisionStatus.NOT_PROVISIONED,
        nullable=False,
    )

    # Exactly one of these is populated depending on employee type's commercial model.
    subscription_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    voice_project_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProvisioningEvent(Base, OrgScopedMixin):
    """Immutable lifecycle audit trail for an EmployeeProvision transition."""

    __tablename__ = "provisioning_events"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.PROVISIONING_EVENT)
    )
    employee_provision_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("employee_provisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String(40))
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
