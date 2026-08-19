from __future__ import annotations

from app.shared.schemas.base import CamelModel


class KnowledgeSourceResponse(CamelModel):
    id: str
    name: str
    type: str
    status: str
    employee_access: list[str]
    document_count: int
    size_bytes: int
    failure_reason: str | None


class ChunkPreviewResponse(CamelModel):
    id: str
    heading: str | None
    excerpt: str


class KnowledgeSourceDetailResponse(KnowledgeSourceResponse):
    version: int
    chunks: list[ChunkPreviewResponse]


class AddUrlSourceRequest(CamelModel):
    name: str
    url: str
    employee_access: list[str]


class SetEmployeeAccessRequest(CamelModel):
    employee_access: list[str]
