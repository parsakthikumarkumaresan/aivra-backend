"""Selects the object storage bucket for a document category.

Spec section 30: separate policies for documents (resumes) vs recordings
(call audio) — each category gets its own bucket/adapter instance so
retention policies can diverge later without touching call sites.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.config import get_settings
from app.shared.storage.base import ObjectStorage
from app.shared.storage.s3_storage import S3ObjectStorage


class StorageCategory(StrEnum):
    DOCUMENTS = "documents"
    RECORDINGS = "recordings"


def get_object_storage(category: StorageCategory) -> ObjectStorage:
    settings = get_settings()
    bucket = (
        settings.object_storage_bucket_documents
        if category == StorageCategory.DOCUMENTS
        else settings.object_storage_bucket_recordings
    )
    return S3ObjectStorage(bucket=bucket)
