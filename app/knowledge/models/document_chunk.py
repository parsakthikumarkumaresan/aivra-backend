from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id

# Must match settings.embedding_dimensions / the configured embedding model
# (text-embedding-3-small = 1536). This is a schema constant, not a runtime
# setting on purpose — changing it requires a real migration (the column's
# dimension is fixed at creation), so it is never read from Settings at
# import time.
EMBEDDING_DIMENSIONS = 1536


class DocumentChunk(Base, OrgScopedMixin):
    """A single retrievable chunk (spec section 12). Organization-scoped by
    ``OrgScopedMixin``; ``knowledge_source_id``/``source_version_id`` give
    full traceability back to the originating source and ingestion run.
    """

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.DOCUMENT_CHUNK)
    )
    knowledge_source_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_version_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("source_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
