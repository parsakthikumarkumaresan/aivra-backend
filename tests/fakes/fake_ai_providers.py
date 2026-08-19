"""In-memory LLM/OCR/storage fakes for testing the resume pipeline without
network calls or real credentials.
"""

from __future__ import annotations

import hashlib

from app.shared.ai_providers.llm import LLMProvider
from app.shared.ai_providers.ocr import OCRProvider
from app.shared.storage.base import ObjectStorage, StoredObject


class FakeOCRProvider(OCRProvider):
    def __init__(self, text: str = "Jane Doe\nSenior Python Engineer\n5 years experience") -> None:
        self.text = text
        self.calls = 0

    async def extract_text(self, *, content: bytes, content_type: str) -> str:
        self.calls += 1
        return self.text


class FakeLLMProvider(LLMProvider):
    """Returns caller-supplied canned responses keyed by schema_name, so a
    single fake can drive both the extraction and matching stages of the
    pipeline within one test.
    """

    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def extract_structured(
        self, *, system_prompt: str, user_content: str, json_schema: dict, schema_name: str
    ) -> dict:
        self.calls.append(schema_name)
        if schema_name not in self.responses:
            raise KeyError(f"FakeLLMProvider has no canned response for {schema_name!r}")
        response = self.responses[schema_name]
        if isinstance(response, Exception):
            raise response
        return response


class FakeObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put_object(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        self._objects[key] = content
        return StoredObject(
            key=key,
            size_bytes=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            content_type=content_type,
        )

    async def get_object(self, *, key: str) -> bytes:
        return self._objects[key]

    async def get_signed_url(self, *, key: str, ttl_seconds: int) -> str:
        return f"https://storage.example.test/{key}?ttl={ttl_seconds}"

    async def delete_object(self, *, key: str) -> None:
        self._objects.pop(key, None)
