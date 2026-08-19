"""Vendor selection for AI providers (ADR 0002: OpenAI for both HR and
Voice). Only the *vendor* is centralized here — the *model* is supplied by
the caller so each AI Employee's scoped factory
(app.ai_employees.hr.ai.provider, app.ai_employees.voice.runtime.llm_provider)
controls its own model choice independently. Swapping the vendor later
touches only this module, never HR/Voice domain code.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.shared.ai_providers.embedding import EmbeddingProvider
from app.shared.ai_providers.llm import LLMProvider
from app.shared.ai_providers.ocr import OCRProvider
from app.shared.ai_providers.openai_embedding_provider import OpenAIEmbeddingProvider
from app.shared.ai_providers.openai_llm_provider import OpenAILLMProvider
from app.shared.ai_providers.pdf_ocr_provider import PdfTextLayerOCRProvider


def get_llm_provider(*, model: str) -> LLMProvider:
    provider = get_settings().llm_provider
    if provider == "openai":
        return OpenAILLMProvider(model=model)
    raise ValueError(f"Unsupported LLM provider configured: {provider!r}")


def get_ocr_provider() -> OCRProvider:
    return PdfTextLayerOCRProvider()


def get_embedding_provider() -> EmbeddingProvider:
    provider = get_settings().llm_provider
    if provider == "openai":
        return OpenAIEmbeddingProvider()
    raise ValueError(f"Unsupported embedding provider configured: {provider!r}")
