"""Knowledge source management (spec section 12). Shared platform (ADR
0003) — callable by any AI Employee context without either importing the
other.
"""

from __future__ import annotations

from app.knowledge.models.source import KnowledgeSource, SourceStatus, SourceType
from app.knowledge.models.source_version import SourceVersion
from app.knowledge.repositories.source_repository import SourceRepository
from app.knowledge.repositories.source_version_repository import SourceVersionRepository
from app.shared.errors.exceptions import NotFoundError
from app.shared.storage.base import ObjectStorage, build_object_key


class KnowledgeService:
    def __init__(
        self,
        source_repo: SourceRepository,
        version_repo: SourceVersionRepository,
        storage: ObjectStorage,
    ) -> None:
        self.source_repo = source_repo
        self.version_repo = version_repo
        self.storage = storage

    async def list_sources(self, organization_id: str) -> list[KnowledgeSource]:
        return await self.source_repo.list_for_organization(organization_id)

    async def get_source(self, organization_id: str, source_id: str) -> KnowledgeSource:
        source = await self.source_repo.get_by_id(organization_id, source_id)
        if source is None:
            raise NotFoundError("Knowledge source not found.")
        return source

    async def get_latest_version(
        self, organization_id: str, source_id: str
    ) -> SourceVersion | None:
        return await self.version_repo.get_latest_for_source(organization_id, source_id)

    async def add_file_source(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        name: str,
        filename: str,
        content: bytes,
        content_type: str,
        employee_access: list[str],
    ) -> tuple[KnowledgeSource, SourceVersion]:
        source = await self.source_repo.add(
            KnowledgeSource(
                organization_id=organization_id,
                name=name,
                type=SourceType.FILE,
                owner_user_id=owner_user_id,
                employee_access=employee_access,
            )
        )
        key = build_object_key(
            organization_id=organization_id,
            category="knowledge",
            object_id=source.id,
            filename=filename,
        )
        await self.storage.put_object(key=key, content=content, content_type=content_type)
        version = await self.version_repo.add(
            SourceVersion(
                organization_id=organization_id,
                knowledge_source_id=source.id,
                version_number=1,
                storage_key=key,
            )
        )
        return source, version

    async def add_url_source(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        name: str,
        url: str,
        employee_access: list[str],
    ) -> tuple[KnowledgeSource, SourceVersion]:
        source = await self.source_repo.add(
            KnowledgeSource(
                organization_id=organization_id,
                name=name,
                type=SourceType.URL,
                owner_user_id=owner_user_id,
                employee_access=employee_access,
            )
        )
        version = await self.version_repo.add(
            SourceVersion(
                organization_id=organization_id,
                knowledge_source_id=source.id,
                version_number=1,
                source_url=url,
            )
        )
        return source, version

    async def reindex(self, organization_id: str, source_id: str) -> SourceVersion:
        source = await self.get_source(organization_id, source_id)
        latest = await self.get_latest_version(organization_id, source_id)
        if latest is None:
            raise NotFoundError("Source has no prior version to re-index from.")
        source.status = SourceStatus.SYNCING
        return await self.version_repo.add(
            SourceVersion(
                organization_id=organization_id,
                knowledge_source_id=source_id,
                version_number=latest.version_number + 1,
                storage_key=latest.storage_key,
                source_url=latest.source_url,
            )
        )

    async def set_employee_access(
        self, organization_id: str, source_id: str, employee_access: list[str]
    ) -> KnowledgeSource:
        source = await self.get_source(organization_id, source_id)
        source.employee_access = employee_access
        return source
