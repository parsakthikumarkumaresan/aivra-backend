"""Voice's scoped entry point to the shared LLM provider infrastructure.

Mirrors app.ai_employees.hr.ai.provider — Voice domain/service code imports
from here, never from app.shared.ai_providers.factory directly, so Voice's
model choice (settings.voice_llm_model) stays independently configurable
from HR's (ADR 0002).
"""

from __future__ import annotations

from app.core.config import get_settings
from app.shared.ai_providers.factory import get_llm_provider
from app.shared.ai_providers.llm import LLMProvider


def get_voice_llm_provider() -> LLMProvider:
    return get_llm_provider(model=get_settings().voice_llm_model)
