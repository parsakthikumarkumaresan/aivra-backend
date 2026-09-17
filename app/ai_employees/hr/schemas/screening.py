from __future__ import annotations

from datetime import datetime

from app.shared.schemas.base import CamelModel


class ScreeningResponse(CamelModel):
    id: str
    candidate_id: str
    status: str
    external_call_ref: str | None
    result_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    # Provider plumbing (livekit_room_name/dispatch_id/sip_participant_identity)
    # is intentionally omitted — internal implementation detail, not a
    # user-facing field (spec section 12).
    prompt_text: str | None
    prompt_generated_at: datetime | None
    prompt_edited_at: datetime | None
    failure_reason: str | None
    transcript: list[dict] | None
    result: dict | None


class CompleteScreeningRequest(CamelModel):
    result_summary: str | None = None


class ScreeningPromptResponse(CamelModel):
    candidate_id: str
    prompt_text: str
    prompt_generated_at: datetime | None
    prompt_edited_at: datetime | None


class UpdateScreeningPromptRequest(CamelModel):
    prompt_text: str


class HrVoiceConfigResponse(CamelModel):
    """Read-only view of HR's screening voice runtime. Mode/provider are
    fixed (settings-driven, org-wide) — HR's screening runtime has no
    per-call or per-org STT/TTS pipeline (app.ai_employees.hr.runtime.
    screening_agent is OpenAI Realtime speech-to-speech only), so this is
    deliberately not an editable form — see spec: don't build UI controls
    for a backend path that doesn't exist.
    """

    mode: str
    realtime_provider: str
    realtime_model: str
    realtime_voice: str
