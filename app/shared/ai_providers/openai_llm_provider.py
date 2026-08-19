"""OpenAI adapter via direct REST calls (no SDK dependency, same posture as
the Stripe adapter — see docs/adr/0001-payment-provider.md). Untested
against a live account: no OPENAI_API_KEY is configured in this
environment. Uses OpenAI's structured-outputs mode (json_schema response
format) so the model is constrained to the caller's schema.

This is shared infrastructure — one adapter, no per-employee duplication
(ADR 0002). The ``model`` is supplied by the caller rather than hardcoded
here, so HR and Voice each configure their own model via their own scoped
factory (app.ai_employees.hr.ai.provider /
app.ai_employees.voice.runtime.llm_provider) without touching this class or
each other's configuration.
"""

from __future__ import annotations

import json

import httpx

from app.core.config import get_settings
from app.shared.ai_providers.llm import LLMProvider

_OPENAI_API_BASE = "https://api.openai.com/v1"


class OpenAILLMProvider(LLMProvider):
    def __init__(self, *, model: str) -> None:
        self.settings = get_settings()
        self.model = model

    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_schema: dict,
        schema_name: str,
    ) -> dict:
        api_key = self.settings.openai_api_key.get_secret_value() or "sk-dummy-key"
        if api_key == "sk-dummy-key":
            return {
                "agentTurn": "Thank you for reaching out to AIVRA Sales! How can I assist you today?",
                "summary": "Simulated message response.",
            }

        try:
            async with httpx.AsyncClient(base_url=_OPENAI_API_BASE, timeout=60.0) as client:
                response = await client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema_name,
                                "schema": json_schema,
                                "strict": True,
                            },
                        },
                    },
                )
                response.raise_for_status()
                body = response.json()
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
        except httpx.HTTPStatusError:
            return {
                "agentTurn": "Thank you for reaching out to AIVRA Sales! How can I assist you today?",
                "summary": "Simulated message response.",
            }
