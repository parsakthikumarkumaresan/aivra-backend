"""OpenAI embeddings adapter — same REST-over-httpx posture as
openai_llm_provider.py. Untested against a live account (ADR 0001 pattern).
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.shared.ai_providers.embedding import EmbeddingProvider

_OPENAI_API_BASE = "https://api.openai.com/v1"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        api_key = self.settings.openai_api_key.get_secret_value() or "sk-dummy-key"
        async with httpx.AsyncClient(base_url=_OPENAI_API_BASE, timeout=60.0) as client:
            response = await client.post(
                "/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": self.settings.embedding_model, "input": texts},
            )
            response.raise_for_status()
            body = response.json()
        return [item["embedding"] for item in body["data"]]
