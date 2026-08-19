from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models.document_chunk import DocumentChunk
from app.knowledge.repositories.source_repository import SourceRepository
from app.knowledge.repositories.source_version_repository import SourceVersionRepository
from app.knowledge.schemas.source import (
    AddUrlSourceRequest,
    ChunkPreviewResponse,
    KnowledgeSourceDetailResponse,
    KnowledgeSourceResponse,
    SetEmployeeAccessRequest,
)
from app.knowledge.services.knowledge_service import KnowledgeService
from app.shared.database.session import get_db
from app.shared.rbac.roles import ORG_MANAGEMENT_ROLES
from app.shared.security.dependencies import AuthContext, require_organization_context, require_role
from app.shared.storage.factory import StorageCategory, get_object_storage
from app.workers.jobs.knowledge_jobs import enqueue_ingestion

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _service(db: AsyncSession = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(
        SourceRepository(db),
        SourceVersionRepository(db),
        get_object_storage(StorageCategory.DOCUMENTS),
    )


@router.get("/sources", response_model=list[KnowledgeSourceResponse])
async def list_sources(
    auth: AuthContext = Depends(require_organization_context),
    service: KnowledgeService = Depends(_service),
) -> list[KnowledgeSourceResponse]:
    sources = await service.list_sources(auth.require_organization_id())
    return [KnowledgeSourceResponse.model_validate(s) for s in sources]


@router.get("/sources/{source_id}", response_model=KnowledgeSourceDetailResponse)
async def get_source(
    source_id: str,
    auth: AuthContext = Depends(require_organization_context),
    service: KnowledgeService = Depends(_service),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeSourceDetailResponse:
    org_id = auth.require_organization_id()
    source = await service.get_source(org_id, source_id)
    version = await service.get_latest_version(org_id, source_id)

    chunks: list[ChunkPreviewResponse] = []
    if version is not None:
        result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.source_version_id == version.id)
            .order_by(DocumentChunk.chunk_index)
            .limit(20)
        )
        chunks = [
            ChunkPreviewResponse(id=c.id, heading=c.heading, excerpt=c.content[:280])
            for c in result.scalars().all()
        ]

    return KnowledgeSourceDetailResponse(
        **KnowledgeSourceResponse.model_validate(source).model_dump(),
        version=version.version_number if version else 0,
        chunks=chunks,
    )


@router.post("/sources/file", response_model=KnowledgeSourceResponse, status_code=201)
async def add_file_source(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    employee_access: str = Form(...),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: KnowledgeService = Depends(_service),
) -> KnowledgeSourceResponse:
    org_id = auth.require_organization_id()
    content = await file.read()
    source, version = await service.add_file_source(
        organization_id=org_id,
        owner_user_id=auth.user.id,
        name=name,
        filename=file.filename or "source",
        content=content,
        content_type=file.content_type or "application/octet-stream",
        employee_access=json.loads(employee_access),
    )
    background_tasks.add_task(
        enqueue_ingestion, organization_id=org_id, source_version_id=version.id
    )
    return KnowledgeSourceResponse.model_validate(source)


@router.post("/sources/url", response_model=KnowledgeSourceResponse, status_code=201)
async def add_url_source(
    payload: AddUrlSourceRequest,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: KnowledgeService = Depends(_service),
) -> KnowledgeSourceResponse:
    org_id = auth.require_organization_id()
    source, version = await service.add_url_source(
        organization_id=org_id,
        owner_user_id=auth.user.id,
        name=payload.name,
        url=payload.url,
        employee_access=payload.employee_access,
    )
    background_tasks.add_task(
        enqueue_ingestion, organization_id=org_id, source_version_id=version.id
    )
    return KnowledgeSourceResponse.model_validate(source)


@router.post("/sources/{source_id}/reindex", response_model=KnowledgeSourceResponse)
async def reindex_source(
    source_id: str,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: KnowledgeService = Depends(_service),
) -> KnowledgeSourceResponse:
    org_id = auth.require_organization_id()
    version = await service.reindex(org_id, source_id)
    background_tasks.add_task(
        enqueue_ingestion, organization_id=org_id, source_version_id=version.id
    )
    source = await service.get_source(org_id, source_id)
    return KnowledgeSourceResponse.model_validate(source)


@router.patch("/sources/{source_id}/access", response_model=KnowledgeSourceResponse)
async def set_employee_access(
    source_id: str,
    payload: SetEmployeeAccessRequest,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: KnowledgeService = Depends(_service),
) -> KnowledgeSourceResponse:
    source = await service.set_employee_access(
        auth.require_organization_id(), source_id, payload.employee_access
    )
    return KnowledgeSourceResponse.model_validate(source)
