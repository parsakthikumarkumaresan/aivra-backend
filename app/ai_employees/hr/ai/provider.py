"""HR's scoped entry point to the shared LLM provider infrastructure.

HR domain/service code must import from here, never from
``app.shared.ai_providers.factory`` directly — that keeps HR's model choice
(``settings.hr_llm_model``) independently configurable from Voice's
(ADR 0002: per-employee AI configuration isolation). The underlying OpenAI
adapter is shared infrastructure; only the configuration is HR-scoped.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.shared.ai_providers.factory import get_llm_provider
from app.shared.ai_providers.llm import LLMProvider


def get_hr_llm_provider() -> LLMProvider:
    return get_llm_provider(model=get_settings().hr_llm_model)
