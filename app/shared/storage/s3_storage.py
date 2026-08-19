"""S3-compatible object storage adapter (works with AWS S3 or MinIO locally).

Untested against a live bucket in this environment (no credentials
configured) — same real-adapter-not-fake-success posture as the Stripe
adapter, see docs/adr/0001-payment-provider.md for the pattern this
follows. boto3 is synchronous; calls are offloaded to a thread so the
async request path is never blocked (spec section 27: never block on
external I/O from within the request/transaction path unnecessarily).
"""

from __future__ import annotations

import asyncio
import hashlib

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import get_settings
from app.shared.storage.base import ObjectStorage, StoredObject


class S3ObjectStorage(ObjectStorage):
    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        settings = get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key_id.get_secret_value() or None,
            aws_secret_access_key=(
                settings.object_storage_secret_access_key.get_secret_value() or None
            ),
            config=BotoConfig(signature_version="s3v4"),
        )
        self._default_signed_url_ttl = settings.object_storage_signed_url_ttl_seconds

    async def put_object(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        checksum = hashlib.sha256(content).hexdigest()

        def _put() -> None:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata={"sha256": checksum},
            )

        await asyncio.to_thread(_put)
        return StoredObject(
            key=key, size_bytes=len(content), checksum_sha256=checksum, content_type=content_type
        )

    async def get_object(self, *, key: str) -> bytes:
        def _get() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def get_signed_url(self, *, key: str, ttl_seconds: int | None = None) -> str:
        def _sign() -> str:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=ttl_seconds or self._default_signed_url_ttl,
            )

        return await asyncio.to_thread(_sign)

    async def delete_object(self, *, key: str) -> None:
        def _delete() -> None:
            self._client.delete_object(Bucket=self.bucket, Key=key)

        await asyncio.to_thread(_delete)
