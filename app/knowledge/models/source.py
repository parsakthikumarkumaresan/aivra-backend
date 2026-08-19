from __future__ import annotations

from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class SourceType(StrEnum):
    FILE = "file"
    URL = "url"
    CONNECTED_SOURCE = "connected_source"


class SourceStatus(StrEnum):
    """Coarse, frontend-facing status — derived from the latest
    SourceVersion's fine-grained ``processing_status`` (see
    app.knowledge.models.source_version.SOURCE_VERSION_TRANSITIONS).
    """

    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"
    STALE = "stale"


class KnowledgeCollection(Base, OrgScopedMixin):
    """A named grouping of sources (spec section 19 DB group:
    ``knowledge_collections``). MVP: one implicit default collection per
    organization is enough — explicit multi-collection UX is a follow-up.
    """

    __tablename__ = "knowledge_collections"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.KNOWLEDGE_COLLECTION)
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class KnowledgeSource(Base, OrgScopedMixin):
    """Shared-platform knowledge source (ADR 0003) — organization-scoped,
    with per-employee-type retrieval access rather than being owned by one
    AI Employee's domain.
    """

    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.KNOWLEDGE_SOURCE)
    )
    collection_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("knowledge_collections.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SourceType] = mapped_column(str_enum_column(SourceType, 20), nullable=False)
    status: Mapped[SourceStatus] = mapped_column(
        str_enum_column(SourceStatus, 20), default=SourceStatus.SYNCING, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Employee type codes (e.g. ["hr", "voice"]) permitted to retrieve from
    # this source — the tenant-safe retrieval filter (spec section 12).
    employee_access: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
