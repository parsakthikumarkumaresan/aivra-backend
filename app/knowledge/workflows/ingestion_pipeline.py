"""Knowledge ingestion pipeline (spec section 12): Validate -> Upload ->
Extract -> Normalize -> Chunk -> Embed -> Store -> Index -> READY.

Runs on a background worker (app.workers.jobs.knowledge_jobs), same
resumable-by-current-status design as the HR resume pipeline
(app.ai_employees.hr.workflows.resume_pipeline) — re-ingestion after a
failure re-enters at VALIDATING (simple, cheap enough not to need the HR
pipeline's per-stage resumability, see SOURCE_VERSION_TRANSITIONS).
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.knowledge.models.document_chunk import DocumentChunk
from app.knowledge.models.source import SourceStatus
from app.knowledge.models.source_version import (
    SOURCE_VERSION_TRANSITIONS,
    SourceProcessingStatus,
    SourceVersion,
)
from app.knowledge.repositories.document_chunk_repository import DocumentChunkRepository
from app.knowledge.repositories.source_repository import SourceRepository
from app.knowledge.repositories.source_version_repository import SourceVersionRepository
from app.shared.ai_providers.factory import get_embedding_provider, get_ocr_provider
from app.shared.storage.factory import StorageCategory, get_object_storage

logger = get_logger(__name__)

_CHUNK_SIZE_CHARS = 1500
_CHUNK_OVERLAP_CHARS = 200


class _IngestionFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _chunk_text(text: str) -> list[str]:
    """Simple overlapping character-window splitter — adequate for MVP
    (spec section 41 discipline); a semantic/token-aware splitter is a
    reasonable future upgrade that would only touch this function.
    """
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE_CHARS
        chunks.append(text[start:end].strip())
        start = end - _CHUNK_OVERLAP_CHARS
    return [c for c in chunks if c]


def _transition(version: SourceVersion, target: SourceProcessingStatus) -> None:
    SOURCE_VERSION_TRANSITIONS.assert_transition_allowed(version.processing_status, target)
    version.processing_status = target


async def run_ingestion_pipeline(
    session: AsyncSession, *, organization_id: str, source_version_id: str
) -> None:
    source_version_repo = SourceVersionRepository(session)
    source_repo = SourceRepository(session)
    chunk_repo = DocumentChunkRepository(session)

    version = await source_version_repo.get_by_id(organization_id, source_version_id)
    if version is None:
        logger.warning("ingestion_source_version_not_found", source_version_id=source_version_id)
        return
    source = await source_repo.get_by_id(organization_id, version.knowledge_source_id)
    if source is None:
        logger.warning("ingestion_source_not_found", source_version_id=source_version_id)
        return

    source.status = SourceStatus.SYNCING
    try:
        raw_bytes = await _extract_raw_content(version)
        _transition(version, SourceProcessingStatus.UPLOADING)

        _transition(version, SourceProcessingStatus.EXTRACTING)
        text = await _extract_text(version, raw_bytes)
        version.raw_text = text

        _transition(version, SourceProcessingStatus.NORMALIZING)
        normalized = " ".join(text.split())
        if not normalized:
            raise _IngestionFailure("No extractable text found in source.")

        _transition(version, SourceProcessingStatus.CHUNKING)
        chunk_texts = _chunk_text(normalized)
        if not chunk_texts:
            raise _IngestionFailure("Source produced no chunks after normalization.")

        _transition(version, SourceProcessingStatus.EMBEDDING)
        embeddings = await get_embedding_provider().embed_texts(chunk_texts)

        _transition(version, SourceProcessingStatus.STORING)
        await chunk_repo.delete_for_source(organization_id, source.id)
        paired = list(enumerate(zip(chunk_texts, embeddings, strict=True)))
        chunks = [
            DocumentChunk(
                organization_id=organization_id,
                knowledge_source_id=source.id,
                source_version_id=version.id,
                chunk_index=index,
                heading=chunk_text.splitlines()[0][:255] if chunk_text else None,
                content=chunk_text,
                embedding=embedding,
            )
            for index, (chunk_text, embedding) in paired
        ]
        await chunk_repo.add_many(chunks)

        _transition(version, SourceProcessingStatus.INDEXING)
        # pgvector's index (ivfflat/hnsw) is created once via migration, not
        # per-ingestion — this stage exists to mirror the spec's pipeline
        # name and is where a future ANN index REFRESH would go.
        _transition(version, SourceProcessingStatus.READY)

        source.status = SourceStatus.SYNCED
        source.document_count = len(chunks)
        source.size_bytes = len(raw_bytes)
        source.failure_reason = None

    except _IngestionFailure as failure:
        _transition(version, SourceProcessingStatus.FAILED)
        version.failure_reason = failure.message
        source.status = SourceStatus.FAILED
        source.failure_reason = failure.message
    except Exception as exc:
        _transition(version, SourceProcessingStatus.FAILED)
        version.failure_reason = str(exc)
        source.status = SourceStatus.FAILED
        source.failure_reason = str(exc)
        logger.exception("ingestion_pipeline_crashed", source_version_id=source_version_id)


async def _extract_raw_content(version: SourceVersion) -> bytes:
    if version.storage_key:
        storage = get_object_storage(StorageCategory.DOCUMENTS)
        try:
            return await storage.get_object(key=version.storage_key)
        except Exception as exc:
            raise _IngestionFailure(f"Could not read stored file: {exc}") from exc
    if version.source_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(version.source_url)
                response.raise_for_status()
                return response.content
        except Exception as exc:
            raise _IngestionFailure(f"Could not fetch URL: {exc}") from exc
    raise _IngestionFailure("Source version has neither a storage_key nor a source_url.")


async def _extract_text(version: SourceVersion, raw_bytes: bytes) -> str:
    if version.storage_key and version.storage_key.lower().endswith(".pdf"):
        try:
            return await get_ocr_provider().extract_text(
                content=raw_bytes, content_type="application/pdf"
            )
        except Exception as exc:
            raise _IngestionFailure(f"Text extraction failed: {exc}") from exc
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _IngestionFailure(f"Could not decode source content as text: {exc}") from exc
