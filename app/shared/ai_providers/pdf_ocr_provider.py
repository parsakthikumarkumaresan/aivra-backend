"""Text-layer extraction for text-based PDFs via ``pypdf``.

This is NOT true optical OCR — it reads the embedded text layer that most
resume PDFs (exported from Word/Google Docs/LaTeX) already contain. A
scanned/image-only PDF has no text layer and will legitimately extract
little or nothing; that limitation is real and intentional for MVP scope
(spec section 41) rather than faked — flagged here instead of silently
producing wrong results. Swapping in a true OCR provider (e.g. an
image-to-text API) later only requires a new ``OCRProvider`` adapter.
"""

from __future__ import annotations

import asyncio
import io

from pypdf import PdfReader

from app.shared.ai_providers.ocr import OCRProvider


class PdfTextLayerOCRProvider(OCRProvider):
    async def extract_text(self, *, content: bytes, content_type: str) -> str:
        if content_type != "application/pdf":
            raise ValueError(
                f"PdfTextLayerOCRProvider only supports application/pdf, got {content_type!r}."
            )

        def _extract() -> str:
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)

        return await asyncio.to_thread(_extract)
