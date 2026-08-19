from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class AgentVersionStatus(StrEnum):
    """Spec section 20: Draft -> Test -> Approve -> Publish, plus rollback.

    Reconciled against the frontend's simpler "bump version on every PATCH"
    model in ADR 0003 — DRAFT is mutable in place (satisfies the frontend's
    PATCH contract); PUBLISHED is immutable forever after (spec: "Published
    configurations must be immutable").
    """

    DRAFT = "draft"
    TEST = "test"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


AGENT_VERSION_TRANSITIONS = StateMachine[AgentVersionStatus](
    {
        AgentVersionStatus.DRAFT: frozenset({AgentVersionStatus.TEST}),
        AgentVersionStatus.TEST: frozenset({AgentVersionStatus.APPROVED, AgentVersionStatus.DRAFT}),
        AgentVersionStatus.APPROVED: frozenset(
            {AgentVersionStatus.PUBLISHED, AgentVersionStatus.DRAFT}
        ),
        AgentVersionStatus.PUBLISHED: frozenset({AgentVersionStatus.ARCHIVED}),
        AgentVersionStatus.ARCHIVED: frozenset(),
    }
)


class AgentVersion(Base, OrgScopedMixin):
    """One immutable-once-published configuration snapshot (spec section
    20) — every field here mirrors one section of the frontend's
    ``VoiceAgent`` type (see ADR 0003), stored as JSON since each section's
    internal shape is UI-owned config, not something the backend needs to
    query into.

    ``tool_ids`` references app.ai_employees.voice.models.tool.Tool rows
    (never embeds a tool definition copy). ``library`` holds
    ``{"knowledgeSourceIds": [...]}`` referencing
    app.knowledge.models.source.KnowledgeSource rows (shared platform, ADR
    0003) — this is the one place Voice reads IDs from the shared Knowledge
    module; it never imports HR domain code to do so.
    """

    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.AGENT_VERSION)
    )
    voice_agent_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("voice_agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AgentVersionStatus] = mapped_column(
        str_enum_column(AgentVersionStatus, 20), default=AgentVersionStatus.DRAFT, nullable=False
    )
    # Only one PUBLISHED version per agent may have is_active=True at a time
    # (enforced in AgentVersionService, not the DB — see spec section 20:
    # "Version 3 (ACTIVE)" implies exactly one active published version).
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    prompt_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    flow_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    context_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    library: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tool_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    voice_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    transcription_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    call_end_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    transfer_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    analysis_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    call_actions_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # AIVRA-internal only — never returned by the customer-safe API (spec
    # section 10.2).
    advanced_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_by_user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
