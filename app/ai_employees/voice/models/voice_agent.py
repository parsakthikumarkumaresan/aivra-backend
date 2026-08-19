from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class VoiceAgentStatus(StrEnum):
    """Matches the frontend's ``VoiceAgentStatus`` exactly. Derived/updated
    by VoiceAgentService as AgentVersions move through their own lifecycle
    (see agent_version.py) — not independently settable to an arbitrary
    value by API callers.
    """

    DRAFT = "draft"
    TESTING = "testing"
    LIVE = "live"
    PAUSED = "paused"


class VoiceAgentEnvironment(StrEnum):
    STAGING = "staging"
    PRODUCTION = "production"


class VoiceAgent(Base, OrgScopedMixin):
    """The agent identity. Its actual behavior lives entirely in
    AgentVersion rows (spec section 20) — this row is the stable ID/name
    plus denormalized display status the frontend reads directly.
    """

    __tablename__ = "voice_agents"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.VOICE_AGENT)
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[VoiceAgentStatus] = mapped_column(
        str_enum_column(VoiceAgentStatus, 20), default=VoiceAgentStatus.DRAFT, nullable=False
    )
    environment: Mapped[VoiceAgentEnvironment] = mapped_column(
        str_enum_column(VoiceAgentEnvironment, 20),
        default=VoiceAgentEnvironment.STAGING,
        nullable=False,
    )
    assigned_phone_number_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True
    )
