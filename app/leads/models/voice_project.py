from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class VoiceProjectStatus(StrEnum):
    """Spec sections 10.3 and 16."""

    LEAD_CREATED = "lead_created"
    DISCOVERY = "discovery"
    REQUIREMENTS_COLLECTED = "requirements_collected"
    CONFIGURATION = "configuration"
    INTEGRATION = "integration"
    TESTING = "testing"
    CUSTOMER_APPROVAL = "customer_approval"
    DEPLOYMENT_PENDING = "deployment_pending"
    ACTIVE = "active"
    CONFIGURATION_FAILED = "configuration_failed"
    INTEGRATION_FAILED = "integration_failed"
    DEPLOYMENT_FAILED = "deployment_failed"


VOICE_PROJECT_TRANSITIONS = StateMachine[VoiceProjectStatus](
    {
        VoiceProjectStatus.LEAD_CREATED: frozenset({VoiceProjectStatus.DISCOVERY}),
        VoiceProjectStatus.DISCOVERY: frozenset({VoiceProjectStatus.REQUIREMENTS_COLLECTED}),
        VoiceProjectStatus.REQUIREMENTS_COLLECTED: frozenset({VoiceProjectStatus.CONFIGURATION}),
        VoiceProjectStatus.CONFIGURATION: frozenset(
            {VoiceProjectStatus.INTEGRATION, VoiceProjectStatus.CONFIGURATION_FAILED}
        ),
        VoiceProjectStatus.CONFIGURATION_FAILED: frozenset({VoiceProjectStatus.CONFIGURATION}),
        VoiceProjectStatus.INTEGRATION: frozenset(
            {VoiceProjectStatus.TESTING, VoiceProjectStatus.INTEGRATION_FAILED}
        ),
        VoiceProjectStatus.INTEGRATION_FAILED: frozenset({VoiceProjectStatus.INTEGRATION}),
        VoiceProjectStatus.TESTING: frozenset(
            {VoiceProjectStatus.CUSTOMER_APPROVAL, VoiceProjectStatus.CONFIGURATION}
        ),
        VoiceProjectStatus.CUSTOMER_APPROVAL: frozenset(
            {VoiceProjectStatus.DEPLOYMENT_PENDING, VoiceProjectStatus.TESTING}
        ),
        VoiceProjectStatus.DEPLOYMENT_PENDING: frozenset(
            {VoiceProjectStatus.ACTIVE, VoiceProjectStatus.DEPLOYMENT_FAILED}
        ),
        VoiceProjectStatus.DEPLOYMENT_FAILED: frozenset({VoiceProjectStatus.DEPLOYMENT_PENDING}),
        VoiceProjectStatus.ACTIVE: frozenset(),
    }
)


class VoiceProject(Base, TimestampMixin):
    """An AIVRA-managed Voice customization project (spec section 16).

    Not org-scoped at creation — ``organization_id`` is set when AIVRA
    provisions the target organization (which may happen before or after
    the technical work, depending on the sales process). Provisioning the
    actual ``EmployeeProvision`` (customer-visible entitlement) only
    happens when this project reaches ACTIVE — see
    app.ai_employees.provisioning and spec section 8: "A Voice lead never
    automatically creates an active subscription."
    """

    __tablename__ = "voice_projects"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.VOICE_PROJECT)
    )
    lead_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[VoiceProjectStatus] = mapped_column(
        str_enum_column(VoiceProjectStatus, 30),
        default=VoiceProjectStatus.LEAD_CREATED,
        nullable=False,
    )
    assigned_engineer_user_id: Mapped[str | None] = mapped_column(String(40))
    failure_reason: Mapped[str | None] = mapped_column(Text)
