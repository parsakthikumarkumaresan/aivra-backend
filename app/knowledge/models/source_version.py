from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class SourceProcessingStatus(StrEnum):
    """Spec section 12: Validate -> Upload -> Extract -> Normalize -> Chunk
    -> Embed -> Store -> Index -> READY.
    """

    VALIDATING = "validating"
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    STORING = "storing"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


SOURCE_VERSION_TRANSITIONS = StateMachine[SourceProcessingStatus](
    {
        SourceProcessingStatus.VALIDATING: frozenset(
            {SourceProcessingStatus.UPLOADING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.UPLOADING: frozenset(
            {SourceProcessingStatus.EXTRACTING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.EXTRACTING: frozenset(
            {SourceProcessingStatus.NORMALIZING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.NORMALIZING: frozenset(
            {SourceProcessingStatus.CHUNKING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.CHUNKING: frozenset(
            {SourceProcessingStatus.EMBEDDING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.EMBEDDING: frozenset(
            {SourceProcessingStatus.STORING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.STORING: frozenset(
            {SourceProcessingStatus.INDEXING, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.INDEXING: frozenset(
            {SourceProcessingStatus.READY, SourceProcessingStatus.FAILED}
        ),
        SourceProcessingStatus.READY: frozenset(),
        # Retryable from the top — re-ingestion re-validates rather than
        # resuming mid-pipeline (unlike the HR resume pipeline, a knowledge
        # re-index is cheap enough not to warrant stage-level resumability).
        SourceProcessingStatus.FAILED: frozenset({SourceProcessingStatus.VALIDATING}),
    }
)


class SourceVersion(Base, OrgScopedMixin):
    """One ingestion run of a KnowledgeSource — re-indexing creates a new
    version rather than overwriting, preserving source/version traceability
    (spec section 12).
    """

    __tablename__ = "source_versions"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.SOURCE_VERSION)
    )
    knowledge_source_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_status: Mapped[SourceProcessingStatus] = mapped_column(
        str_enum_column(SourceProcessingStatus, 20),
        default=SourceProcessingStatus.VALIDATING,
        nullable=False,
    )
    storage_key: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    raw_text: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
