from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.shared.schemas.base import CamelModel


class CreateVoiceAgentRequest(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=120)


class UpdateVoiceAgentDraftRequest(CamelModel):
    patch: dict[str, Any]


class RollbackVoiceAgentRequest(CamelModel):
    target_version_id: str


class VoiceAgentResponse(CamelModel):
    id: str
    organization_id: str
    name: str
    industry: str | None
    status: str
    environment: str
    version: int
    last_updated_at: datetime
    assigned_phone_number_id: str | None = None
    prompt_config: dict[str, Any]
    flow_config: dict[str, Any]
    context_config: dict[str, Any]
    library: dict[str, Any]
    tools: list[dict[str, Any]]
    voice_config: dict[str, Any]
    transcription_config: dict[str, Any]
    call_end_config: dict[str, Any]
    transfer_config: dict[str, Any]
    analysis_config: dict[str, Any]
    call_actions_config: dict[str, Any]
    advanced_config: dict[str, Any]


class AgentVersionResponse(CamelModel):
    id: str
    voice_agent_id: str
    version_number: int
    status: str
    is_active: bool
    prompt_config: dict[str, Any]
    flow_config: dict[str, Any]
    context_config: dict[str, Any]
    library: dict[str, Any]
    tool_ids: list[str]
    voice_config: dict[str, Any]
    transcription_config: dict[str, Any]
    call_end_config: dict[str, Any]
    transfer_config: dict[str, Any]
    analysis_config: dict[str, Any]
    call_actions_config: dict[str, Any]
    advanced_config: dict[str, Any]
    published_at: datetime | None = None


class TestMessageRequest(CamelModel):
    user_text: str


class TestTurnResultResponse(CamelModel):
    user_turn: dict[str, Any]
    agent_turn: dict[str, Any]
    debug: dict[str, Any]


class ReplayToolCall(CamelModel):
    id: str
    name: str
    input: str
    output: str
    status: str
    timestamp: str


class ReplayTimelineEntry(CamelModel):
    id: str
    label: str
    timestamp: str


class ReplayConversationResponse(CamelModel):
    id: str
    agent_id: str
    customer_name: str
    duration_seconds: int
    outcome: str
    started_at: datetime
    transcript: list[dict[str, Any]]
    tool_calls: list[ReplayToolCall]
    knowledge_retrieved: list[str]
    timeline: list[ReplayTimelineEntry]
