from __future__ import annotations

from app.ai_employees.voice.runtime.base import VoiceRuntimeProvider
from app.ai_employees.voice.runtime.livekit_provider import LiveKitRuntimeProvider


def get_voice_runtime_provider() -> VoiceRuntimeProvider:
    return LiveKitRuntimeProvider()
