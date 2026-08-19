from __future__ import annotations

from datetime import datetime
from typing import Any

from app.shared.schemas.base import CamelModel


class CustomerVoiceToolSummary(CamelModel):
    id: str
    name: str
    description: str
    permission: str = "allow"
    risk: str = "low"
    approval_required: bool = False
    connected: bool = True


class CustomerEscalationRule(CamelModel):
    trigger: str
    label: str
    description: str
    enabled: bool = True


class VoiceNotificationPreferences(CamelModel):
    escalations: bool = True
    daily_summary: bool = True
    missed_calls: bool = True


class VoiceBasicEscalationPreferences(CamelModel):
    upset_caller: bool = True
    refunds_or_cancellations: bool = True


class VoiceEmployeeConfigResponse(CamelModel):
    business_name: str
    industry: str
    description: str
    timezone: str
    working_hours: str
    language: str
    voice: str
    tone: str
    greeting: str
    fallback_message: str
    speaking_style: str
    knowledge_source_ids: list[str]
    capabilities: list[str]
    tools: list[CustomerVoiceToolSummary]
    escalation_rules: list[CustomerEscalationRule]
    phone_provider: str
    phone_number: str
    inbound_enabled: bool
    outbound_enabled: bool
    employee_name: str
    notification_preferences: VoiceNotificationPreferences
    basic_escalation_preferences: VoiceBasicEscalationPreferences


class CustomerToolExecutionSummary(CamelModel):
    id: str
    tool_name: str
    input: str
    result: str
    status: str
    latency_ms: int
    timestamp: datetime


class CustomerCallResponse(CamelModel):
    id: str
    caller_name: str
    caller_number: str
    employee_id: str
    started_at: datetime
    duration_seconds: int
    intent: str
    outcome: str
    escalated: bool
    escalation_reason: str | None = None
    recording_available: bool
    summary: str
    transcript: list[dict[str, Any]]
    tools_used: list[CustomerToolExecutionSummary]
    actions_taken: list[str]


class SimulatorRequest(CamelModel):
    scenario: str
    user_text: str | None = None


class SimulatorResultResponse(CamelModel):
    outcome: str
    transcript: list[dict[str, Any]]
    failed_step: str | None = None
    tool_result: str | None = None
    configuration_suggestion: str | None = None
