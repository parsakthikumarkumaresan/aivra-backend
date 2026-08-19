from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CallIntent(StrEnum):
    FAQ = "faq"
    BOOKING = "booking"
    CANCELLATION = "cancellation"
    STATUS_LOOKUP = "status_lookup"
    COMPLAINT = "complaint"
    UNKNOWN = "unknown"


class CallOutcome(StrEnum):
    RESOLVED = "resolved"
    BOOKED = "booked"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"
    NO_ACTION = "no_action"
    FAILED = "failed"


class Call(Base, OrgScopedMixin):
    """Every field the Definition of Done requires: call/session ID,
    provider call ID, org, employee, exact config version, direction,
    timestamps, duration, outcome, transfer status, recording/transcript
    presence flags.
    """

    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CALL)
    )
    voice_agent_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("voice_agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The exact published configuration that handled this call (spec
    # section 20: "every call references the exact published configuration
    # version").
    agent_version_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    provider_call_id: Mapped[str | None] = mapped_column(String(120))
    room_name: Mapped[str | None] = mapped_column(String(255))
    caller_name: Mapped[str | None] = mapped_column(String(255))
    caller_number: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[CallDirection] = mapped_column(
        str_enum_column(CallDirection, 20), nullable=False
    )
    status: Mapped[CallStatus] = mapped_column(
        str_enum_column(CallStatus, 20), default=CallStatus.IN_PROGRESS, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    intent: Mapped[CallIntent | None] = mapped_column(str_enum_column(CallIntent, 20))
    outcome: Mapped[CallOutcome | None] = mapped_column(str_enum_column(CallOutcome, 20))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    recording_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
