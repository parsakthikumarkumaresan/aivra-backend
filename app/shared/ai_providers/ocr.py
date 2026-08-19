"""OCR/document-text-extraction provider abstraction (spec sections 21, 29)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class OCRProvider(ABC):
    @abstractmethod
    async def extract_text(self, *, content: bytes, content_type: str) -> str: ...
