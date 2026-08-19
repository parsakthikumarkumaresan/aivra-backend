"""OpenAI adapter via direct REST calls (no SDK dependency, same posture as
the Stripe adapter — see docs/adr/0001-payment-provider.md). Uses OpenAI's
structured-outputs mode (json_schema response format) so the model is
constrained to the caller's schema.

This is shared infrastructure — one adapter, no per-employee duplication
(ADR 0002). The ``model`` is supplied by the caller rather than hardcoded
here, so HR and Voice each configure their own model via their own scoped
factory (app.ai_employees.hr.ai.provider /
app.ai_employees.voice.runtime.llm_provider) without touching this class or
each other's configuration.

Errors are never swallowed here: a missing API key or a failed OpenAI call
raises, and the caller's own pipeline is responsible for turning that into
the correct failure state (see app.ai_employees.hr.workflows.resume_pipeline
._StageFailure, which maps this exception into EXTRACTION_FAILED /
MATCHING_FAILED). A version of this file once silently returned a
hardcoded, wrongly-shaped fake response on any OpenAI error — that is
exactly the "no fake completion" failure mode the project rules forbid, and
it is not reintroduced here.
"""

from __future__ import annotations

import json

import httpx

from app.core.config import get_settings
from app.shared.ai_providers.llm import LLMProvider
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppError

_OPENAI_API_BASE = "https://api.openai.com/v1"


class OpenAIConfigurationError(AppError):
    status_code = 503
    code = ErrorCode.INTERNAL_ERROR


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
        api_key = self.settings.openai_api_key.get_secret_value()
        if not api_key:
            raise OpenAIConfigurationError(
                "OPENAI_API_KEY is not configured — cannot call OpenAI. This must "
                "propagate as a real failure, not a fabricated response."
            )

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
