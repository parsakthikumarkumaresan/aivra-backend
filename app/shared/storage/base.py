"""Private object storage abstraction (spec sections 22, 30).

Every stored object lives under an organization-scoped key
(``{organization_id}/{category}/{object_id}/{filename}``) so a leaked or
misrouted key can never resolve into another tenant's data. Callers never
get a raw bucket URL — only short-lived signed URLs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str


class ObjectStorage(ABC):
    @abstractmethod
    async def put_object(
        self, *, key: str, content: bytes, content_type: str
    ) -> StoredObject: ...

    @abstractmethod
    async def get_object(self, *, key: str) -> bytes:
        """Server-side read (e.g. for a background worker to run OCR on a
        stored file). Never exposed to clients — they only ever get a
        signed URL via ``get_signed_url``.
        """
        ...

    @abstractmethod
    async def get_signed_url(self, *, key: str, ttl_seconds: int) -> str: ...

    @abstractmethod
    async def delete_object(self, *, key: str) -> None: ...


def build_object_key(
    *, organization_id: str, category: str, object_id: str, filename: str
) -> str:
    safe_filename = filename.replace("/", "_").replace("\\", "_")
    return f"{organization_id}/{category}/{object_id}/{safe_filename}"
