from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models.document_chunk import DocumentChunk


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(self, chunks: list[DocumentChunk]) -> None:
        self.session.add_all(chunks)
        await self.session.flush()

    async def delete_for_source(self, organization_id: str, knowledge_source_id: str) -> None:
        stmt = delete(DocumentChunk).where(
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.knowledge_source_id == knowledge_source_id,
        )
        await self.session.execute(stmt)

    async def similarity_search(
        self,
        organization_id: str,
        *,
        query_embedding: list[float],
        allowed_source_ids: list[str],
        limit: int,
    ) -> list[DocumentChunk]:
        """Tenant-safe retrieval: ``allowed_source_ids`` must already be
        filtered to sources both org-scoped AND employee-access-scoped by
        the caller (see KnowledgeService.retrieve) — this method has no
        way to enforce that on its own, so it never runs unscoped.
        """
        if not allowed_source_ids:
            return []
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.knowledge_source_id.in_(allowed_source_ids),
            )
            .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
