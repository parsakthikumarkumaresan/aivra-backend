"""Tenant-safe RAG retrieval (spec section 12). The only path any AI
Employee runtime uses to pull knowledge context — enforces organization
scope AND employee-type access on every query.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.models.source import SourceStatus
from app.knowledge.repositories.document_chunk_repository import DocumentChunkRepository
from app.knowledge.repositories.source_repository import SourceRepository
from app.shared.ai_providers.embedding import EmbeddingProvider


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    knowledge_source_id: str
    source_name: str
    heading: str | None
    content: str


class RetrievalService:
    def __init__(
        self,
        source_repo: SourceRepository,
        chunk_repo: DocumentChunkRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.source_repo = source_repo
        self.chunk_repo = chunk_repo
        self.embedding_provider = embedding_provider

    async def retrieve(
        self, organization_id: str, *, employee_type: str, query: str, limit: int = 5
    ) -> list[RetrievedChunk]:
        sources = await self.source_repo.list_for_organization(organization_id)
        allowed_sources = {
            s.id: s
            for s in sources
            if s.status == SourceStatus.SYNCED and employee_type in s.employee_access
        }
        if not allowed_sources:
            return []

        [query_embedding] = await self.embedding_provider.embed_texts([query])
        chunks = await self.chunk_repo.similarity_search(
            organization_id,
            query_embedding=query_embedding,
            allowed_source_ids=list(allowed_sources.keys()),
            limit=limit,
        )
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                knowledge_source_id=chunk.knowledge_source_id,
                source_name=allowed_sources[chunk.knowledge_source_id].name,
                heading=chunk.heading,
                content=chunk.content,
            )
            for chunk in chunks
        ]
