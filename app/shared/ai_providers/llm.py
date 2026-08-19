"""LLM provider abstraction (spec sections 21, 29, 41).

The only method needed so far is schema-constrained structured extraction —
every AI-critical operation in the spec (candidate extraction, JD matching/
scoring, post-call analysis) requires validated structured output, not
free-form text (spec section 41: "AI output is validated against schemas/
business rules before trusted use").
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_schema: dict,
        schema_name: str,
    ) -> dict:
        """Returns a dict guaranteed (by the provider's structured-output
        mode) to conform to ``json_schema``. Callers still validate against
        their own Pydantic model before treating it as trusted business
        data — provider-level schema conformance is not the same as
        business-rule validity.
        """
        ...
