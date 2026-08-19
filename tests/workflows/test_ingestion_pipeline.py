"""Direct tests of the knowledge ingestion pipeline (spec section 12) —
happy path, a mid-pipeline failure, and tenant/employee-scoped retrieval.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models.user import User
from app.knowledge.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.knowledge.models.source import KnowledgeSource, SourceStatus, SourceType
from app.knowledge.models.source_version import SourceProcessingStatus, SourceVersion
from app.knowledge.repositories.document_chunk_repository import DocumentChunkRepository
from app.knowledge.repositories.source_repository import SourceRepository
from app.knowledge.repositories.source_version_repository import SourceVersionRepository
from app.knowledge.services.retrieval_service import RetrievalService
from app.knowledge.workflows import ingestion_pipeline
from app.organizations.models.organization import Organization
from app.shared.security.passwords import hash_password
from tests.fakes.fake_ai_providers import FakeObjectStorage


def _unit_vector(active_dim: int) -> list[float]:
    """A DocumentChunk.embedding column is a fixed Vector(1536) — every
    embedding, real or fake, must have exactly EMBEDDING_DIMENSIONS floats
    or Postgres rejects the insert. This gives a simple one-hot vector for
    deterministic similarity-search assertions.
    """
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[active_dim] = 1.0
    return vector


class _FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        # Deterministic per-text vector so similarity search is testable.
        return [_unit_vector(hash(t) % EMBEDDING_DIMENSIONS) for t in texts]


class _FakeHttpResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


async def _seed_org_and_owner(db_session: AsyncSession) -> tuple[Organization, User]:
    org = Organization(name="Acme", slug="acme-knowledge-test")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@example.com",
        password_hash=hash_password("SuperSecret123!"),
        full_name="Owner",
    )
    db_session.add(user)
    await db_session.flush()
    return org, user


def _patch_providers(monkeypatch: pytest.MonkeyPatch, storage, embedding_provider) -> None:
    monkeypatch.setattr(
        ingestion_pipeline, "get_object_storage", lambda category: storage  # noqa: ARG005
    )
    monkeypatch.setattr(ingestion_pipeline, "get_embedding_provider", lambda: embedding_provider)


async def test_ingestion_pipeline_happy_path_url_source(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, user = await _seed_org_and_owner(db_session)
    source = KnowledgeSource(
        organization_id=org.id,
        name="FAQ",
        type=SourceType.URL,
        owner_user_id=user.id,
        employee_access=["hr", "voice"],
    )
    db_session.add(source)
    await db_session.flush()

    version = SourceVersion(
        organization_id=org.id,
        knowledge_source_id=source.id,
        version_number=1,
        source_url="https://example.test/faq.txt",
    )
    db_session.add(version)
    await db_session.flush()

    storage = FakeObjectStorage()
    embedding_provider = _FakeEmbeddingProvider()
    _patch_providers(monkeypatch, storage, embedding_provider)

    body_text = "Q: What are your hours?\nA: 9 to 5, Monday to Friday.\n" * 60

    async def _fake_get(self, url, **kwargs):  # noqa: ANN001, ARG001
        return _FakeHttpResponse(body_text.encode("utf-8"))

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    await ingestion_pipeline.run_ingestion_pipeline(
        db_session, organization_id=org.id, source_version_id=version.id
    )

    source_row = await SourceRepository(db_session).get_by_id(org.id, source.id)
    assert source_row is not None
    assert source_row.status == SourceStatus.SYNCED
    assert source_row.document_count > 0

    version_row = await SourceVersionRepository(db_session).get_by_id(org.id, version.id)
    assert version_row is not None
    assert version_row.processing_status == SourceProcessingStatus.READY
    assert embedding_provider.calls  # embed_texts was actually invoked


async def test_ingestion_pipeline_failure_when_no_content_source(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, user = await _seed_org_and_owner(db_session)
    source = KnowledgeSource(
        organization_id=org.id,
        name="Broken",
        type=SourceType.URL,
        owner_user_id=user.id,
        employee_access=["voice"],
    )
    db_session.add(source)
    await db_session.flush()
    version = SourceVersion(
        organization_id=org.id, knowledge_source_id=source.id, version_number=1
    )
    db_session.add(version)
    await db_session.flush()

    _patch_providers(monkeypatch, FakeObjectStorage(), _FakeEmbeddingProvider())

    await ingestion_pipeline.run_ingestion_pipeline(
        db_session, organization_id=org.id, source_version_id=version.id
    )

    source_row = await SourceRepository(db_session).get_by_id(org.id, source.id)
    assert source_row is not None
    assert source_row.status == SourceStatus.FAILED
    assert "neither a storage_key nor a source_url" in (source_row.failure_reason or "")


async def test_retrieval_is_scoped_by_employee_access(db_session: AsyncSession) -> None:
    org, user = await _seed_org_and_owner(db_session)

    hr_only_source = KnowledgeSource(
        organization_id=org.id,
        name="HR Policy",
        type=SourceType.URL,
        owner_user_id=user.id,
        employee_access=["hr"],
        status=SourceStatus.SYNCED,
    )
    voice_source = KnowledgeSource(
        organization_id=org.id,
        name="Voice FAQ",
        type=SourceType.URL,
        owner_user_id=user.id,
        employee_access=["voice"],
        status=SourceStatus.SYNCED,
    )
    db_session.add_all([hr_only_source, voice_source])
    await db_session.flush()

    hr_version = SourceVersion(
        organization_id=org.id, knowledge_source_id=hr_only_source.id, version_number=1
    )
    voice_version = SourceVersion(
        organization_id=org.id, knowledge_source_id=voice_source.id, version_number=1
    )
    db_session.add_all([hr_version, voice_version])
    await db_session.flush()

    db_session.add_all(
        [
            DocumentChunk(
                organization_id=org.id,
                knowledge_source_id=hr_only_source.id,
                source_version_id=hr_version.id,
                chunk_index=0,
                content="HR-only content",
                embedding=_unit_vector(0),
            ),
            DocumentChunk(
                organization_id=org.id,
                knowledge_source_id=voice_source.id,
                source_version_id=voice_version.id,
                chunk_index=0,
                content="Voice-only content",
                embedding=_unit_vector(1),
            ),
        ]
    )
    await db_session.flush()

    retrieval = RetrievalService(
        SourceRepository(db_session), DocumentChunkRepository(db_session), _FakeEmbeddingProvider()
    )

    voice_results = await retrieval.retrieve(org.id, employee_type="voice", query="anything")
    assert all(r.knowledge_source_id == voice_source.id for r in voice_results)
    assert not any(r.knowledge_source_id == hr_only_source.id for r in voice_results)
