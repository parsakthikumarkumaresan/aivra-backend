"""Runtime factory: turns Jaan's normalized voice-provider configuration
into real ``livekit.plugins.*`` STT/TTS client instances for the live-call
worker (app/workers/voice_agent_worker.py).

This is the "provider registry" expressed as a factory — mirroring the
ABC -> implementation -> factory idiom used in app.shared.ai_providers,
adapted here because the concrete "implementation" is an official LiveKit
Agents plugin class (already a real, network-calling client) rather than a
hand-written HTTP client. app.ai_employees.voice.providers.catalog answers
"what is allowed"; this module answers "how to construct it."

Only ever imported by the LiveKit Agents worker process — never by the
FastAPI request path — so it is the one place allowed to construct clients
that hold provider API keys in memory for a live audio session.
"""

from __future__ import annotations

from livekit.agents import stt as stt_base
from livekit.agents import tts as tts_base
from livekit.plugins import elevenlabs, openai, sarvam
from livekit.plugins.openai.realtime import RealtimeModel

from app.core.config import Settings


def build_stt(
    *, provider: str, model: str, language: str | None, settings: Settings
) -> stt_base.STT:
    if provider == "openai":
        return openai.STT(model=model, api_key=settings.openai_api_key.get_secret_value())
    if provider == "elevenlabs":
        return elevenlabs.STT(
            model=model,
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            server_vad=elevenlabs.stt.VADOptions(
                vad_silence_threshold_secs=0.8,
                min_speech_duration_ms=200,
                min_silence_duration_ms=500,
            ),
        )
    if provider == "sarvam":
        # "en-IN" matches sarvam.STT's own constructor default — verified
        # against the installed livekit-plugins-sarvam package rather than
        # guessed; there is no "auto" language sentinel accepted here.
        return sarvam.STT(
            model=model,
            language=language or "en-IN",
            api_key=settings.sarvam_api_key.get_secret_value(),
        )
    raise ValueError(f"Unsupported STT provider: {provider!r}")


def build_tts(
    *, provider: str, model: str, voice_id: str, language: str | None, settings: Settings
) -> tts_base.TTS:
    if provider == "openai":
        return openai.TTS(
            model=model, voice=voice_id, api_key=settings.openai_api_key.get_secret_value()
        )
    if provider == "elevenlabs":
        return elevenlabs.TTS(
            model=model,
            voice_id=voice_id,
            api_key=settings.elevenlabs_api_key.get_secret_value(),
        )
    if provider == "sarvam":
        return sarvam.TTS(
            model=model,
            speaker=voice_id,
            target_language_code=language or "en-IN",
            api_key=settings.sarvam_api_key.get_secret_value(),
        )
    raise ValueError(f"Unsupported TTS provider: {provider!r}")


def build_realtime_model(
    *, provider: str, model: str, voice: str, settings: Settings
) -> RealtimeModel:
    """OpenAI Realtime is the only speech-to-speech provider today (see
    providers/catalog.py:validate_realtime — enforced server-side, not just
    here). Mirrors app.ai_employees.hr.runtime.screening_agent's proven
    working RealtimeModel construction exactly.
    """
    if provider != "openai":
        raise ValueError(f"Unsupported realtime provider: {provider!r}")
    return RealtimeModel(
        model=model, voice=voice, api_key=settings.openai_api_key.get_secret_value()
    )
