"""Centralized, hand-curated catalog of real voice providers, models, and
voices for Jaan (app.ai_employees.voice).

Pure data + pure validation functions — no I/O, no Settings, no secrets.
This is the ONE place to add a new ElevenLabs voice ID or Sarvam speaker;
see the "VOICE ID CONFIGURATION" sections below for exactly where.

Runtime instantiation (the actual livekit.plugins.* client objects) lives
in app.ai_employees.voice.runtime.voice_pipeline — that module answers "how
to construct a live client"; this module only answers "what is allowed."

Editing this file requires restarting the FastAPI process (for
GET /internal/voice-agents/providers and PATCH validation) and the LiveKit
voice-agent worker process (for live calls to pick up a new voice) — Python
does not hot-reload modules.
"""

from __future__ import annotations

from app.shared.errors.exceptions import ValidationAppError

PROVIDER_CAPABILITIES: dict[str, list[str]] = {
    "openai": ["realtime", "stt", "tts", "llm"],
    "elevenlabs": ["stt", "tts"],
    "sarvam": ["stt", "tts"],
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "elevenlabs": "ElevenLabs",
    "sarvam": "Sarvam AI",
}

# ---------------------------------------------------------------------------
# OpenAI Realtime (speech-to-speech) — the only Realtime provider today.
# ---------------------------------------------------------------------------
# Current production model per OpenAI's gpt-realtime release (August 2025).
# gpt-4o-realtime-preview is the deprecated predecessor — do not re-add it.
REALTIME_MODELS: list[str] = ["gpt-realtime"]

# Curated subset of the documented Realtime voice set. marin/cedar are
# OpenAI's recommended, Realtime-exclusive voices (same ones already used by
# Jexa HR's screening runtime — app/ai_employees/hr/runtime/screening_agent.py).
REALTIME_VOICES: list[dict[str, str]] = [
    {"id": "marin", "name": "Marin", "description": "Recommended — natural, warm"},
    {"id": "cedar", "name": "Cedar", "description": "Recommended — natural, grounded"},
    {"id": "alloy", "name": "Alloy", "description": "Neutral and balanced"},
    {"id": "verse", "name": "Verse", "description": "Versatile and expressive"},
    {"id": "coral", "name": "Coral", "description": "Warm and friendly"},
    {"id": "sage", "name": "Sage", "description": "Calm and thoughtful"},
]

# ---------------------------------------------------------------------------
# OpenAI — Custom STT/TTS/LLM mode
# ---------------------------------------------------------------------------
OPENAI_STT_MODELS: list[str] = ["gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
OPENAI_TTS_MODELS: list[str] = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]

# ============================================================================
# VOICE ID CONFIGURATION — OpenAI (non-realtime TTS)
# ============================================================================
# OpenAI's standard TTS voices are fixed, documented names (not
# account-specific) — safe to list in full. To add/remove one, edit this list.
OPENAI_TTS_VOICES: list[dict[str, str]] = [
    {"id": "alloy", "name": "Alloy", "description": "Neutral"},
    {"id": "echo", "name": "Echo", "description": "Resonant"},
    {"id": "fable", "name": "Fable", "description": "Expressive"},
    {"id": "onyx", "name": "Onyx", "description": "Deep"},
    {"id": "nova", "name": "Nova", "description": "Bright"},
    {"id": "shimmer", "name": "Shimmer", "description": "Energetic"},
]

OPENAI_LLM_MODELS: list[str] = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-5-mini"]

# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------
ELEVENLABS_STT_MODELS: list[str] = ["scribe_v2_realtime"]
ELEVENLABS_TTS_MODELS: list[str] = [
    "eleven_flash_v2_5",
    "eleven_turbo_v2_5",
    "eleven_multilingual_v2",
]

# ============================================================================
# VOICE ID CONFIGURATION — ElevenLabs  <-- ADD YOUR VOICE IDS HERE
# ============================================================================
# ElevenLabs voice IDs are opaque, ACCOUNT-SPECIFIC strings (found in your
# ElevenLabs dashboard under Voice Library / My Voices). They cannot be
# guessed or auto-populated — this list is deliberately empty until you add
# real ones. To add a voice, append one dict in this exact shape:
#
#   {"id": "<real ElevenLabs voice_id from your account>",
#    "name": "<display name>",
#    "language": "en",
#    "gender": "female" | "male" | "neutral",
#    "description": "<optional short description>"}
#
# No other code changes are needed — restart the API and worker processes
# to pick up the change.
ELEVENLABS_VOICES: list[dict[str, str]] = [
    # Example shape only — NOT a usable ID, replace with a real one from your account:
    # {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "language": "en",
    #  "gender": "female", "description": "Example placeholder"},
]

# ---------------------------------------------------------------------------
# Sarvam AI
# ---------------------------------------------------------------------------
# Verified against the actually-installed livekit-plugins-sarvam==1.6.10
# package (livekit/plugins/sarvam/stt.py:SarvamSTTModels) rather than
# assumed from docs. "saarika" is Sarvam's general transcription family;
# "saaras" is speech-*translation* (to English) — both are exposed here
# since the `mode` param controls transcribe vs. translate behavior.
SARVAM_STT_MODELS: list[str] = ["saarika:v2.5", "saaras:v2.5", "saaras:v3"]
SARVAM_STT_MODES: list[str] = ["transcribe", "translate", "verbatim", "translit", "codemix"]
SARVAM_TTS_MODELS: list[str] = ["bulbul:v3", "bulbul:v3-beta", "bulbul:v2"]

# ============================================================================
# VOICE ID CONFIGURATION — Sarvam  <-- ADD/REMOVE SPEAKERS HERE
# ============================================================================
# Unlike ElevenLabs, Sarvam's speakers are fixed, model-level names (not
# account-specific) — these are the real documented speaker names per model.
# To curate which ones Jaan actually offers, add/remove entries below.

# Verified against livekit-plugins-sarvam==1.6.10's own
# MODEL_SPEAKER_COMPATIBILITY mapping (livekit/plugins/sarvam/tts.py) — a
# curated subset of the speakers actually compatible with each model, not
# the full ~30-speaker list.
_BULBUL_V3_SPEAKERS: list[dict[str, str]] = [
    {"id": "shubh", "name": "Shubh", "gender": "male"},
    {"id": "aditya", "name": "Aditya", "gender": "male"},
    {"id": "amit", "name": "Amit", "gender": "male"},
    {"id": "aayan", "name": "Aayan", "gender": "male"},
    {"id": "amelia", "name": "Amelia", "gender": "female"},
    {"id": "ishita", "name": "Ishita", "gender": "female"},
    {"id": "kavya", "name": "Kavya", "gender": "female"},
    {"id": "priya", "name": "Priya", "gender": "female"},
]
SARVAM_VOICES: dict[str, list[dict[str, str]]] = {
    "bulbul:v3": _BULBUL_V3_SPEAKERS,
    "bulbul:v3-beta": _BULBUL_V3_SPEAKERS,
    "bulbul:v2": [
        {"id": "anushka", "name": "Anushka", "gender": "female"},
        {"id": "arya", "name": "Arya", "gender": "female"},
        {"id": "manisha", "name": "Manisha", "gender": "female"},
        {"id": "abhilash", "name": "Abhilash", "gender": "male"},
        {"id": "hitesh", "name": "Hitesh", "gender": "male"},
    ],
}

# ---------------------------------------------------------------------------
# Ambient sound
# ---------------------------------------------------------------------------
# Maps a stable catalog id (persisted in voice_config.backgroundSoundId) to
# the livekit.agents BuiltinAudioClip member name consumed by
# app.ai_employees.voice.runtime.voice_pipeline. Add more by picking another
# BuiltinAudioClip member and adding a row here.
AMBIENT_SOUNDS: list[dict[str, str]] = [
    {"id": "office_ambience", "name": "Office Ambience", "clip": "OFFICE_AMBIENCE"},
    {"id": "keyboard_typing", "name": "Keyboard Typing", "clip": "KEYBOARD_TYPING"},
]

TURN_DETECTION_MODES: list[str] = ["heuristic", "semantic", "fixed_silence"]


def _stt_models(provider: str) -> list[str]:
    return {
        "openai": OPENAI_STT_MODELS,
        "elevenlabs": ELEVENLABS_STT_MODELS,
        "sarvam": SARVAM_STT_MODELS,
    }.get(provider, [])


def _tts_models(provider: str) -> list[str]:
    return {
        "openai": OPENAI_TTS_MODELS,
        "elevenlabs": ELEVENLABS_TTS_MODELS,
        "sarvam": SARVAM_TTS_MODELS,
    }.get(provider, [])


def _tts_voice_ids(provider: str, model: str) -> list[str]:
    if provider == "openai":
        return [v["id"] for v in OPENAI_TTS_VOICES]
    if provider == "elevenlabs":
        return [v["id"] for v in ELEVENLABS_VOICES]
    if provider == "sarvam":
        return [v["id"] for v in SARVAM_VOICES.get(model, [])]
    return []


def validate_realtime(*, provider: str, model: str, voice: str) -> None:
    if provider != "openai":
        raise ValidationAppError(
            f"Realtime mode only supports the OpenAI provider today, got {provider!r}."
        )
    if model not in REALTIME_MODELS:
        raise ValidationAppError(f"Unknown realtime model {model!r}. Allowed: {REALTIME_MODELS}")
    allowed_voices = [v["id"] for v in REALTIME_VOICES]
    if voice not in allowed_voices:
        raise ValidationAppError(f"Unknown realtime voice {voice!r}. Allowed: {allowed_voices}")


def validate_stt(*, provider: str, model: str) -> None:
    if "stt" not in PROVIDER_CAPABILITIES.get(provider, []):
        raise ValidationAppError(f"{provider!r} does not support STT.")
    if model not in _stt_models(provider):
        raise ValidationAppError(f"Unknown STT model {model!r} for provider {provider!r}.")


def validate_tts(*, provider: str, model: str, voice_id: str) -> None:
    if "tts" not in PROVIDER_CAPABILITIES.get(provider, []):
        raise ValidationAppError(f"{provider!r} does not support TTS.")
    if model not in _tts_models(provider):
        raise ValidationAppError(f"Unknown TTS model {model!r} for provider {provider!r}.")
    allowed_voices = _tts_voice_ids(provider, model)
    if provider == "elevenlabs" and not allowed_voices:
        raise ValidationAppError(
            "No ElevenLabs voices are configured yet. Add a real voice ID to "
            "app/ai_employees/voice/providers/catalog.py:ELEVENLABS_VOICES before "
            "selecting this provider."
        )
    if voice_id not in allowed_voices:
        raise ValidationAppError(
            f"Voice {voice_id!r} does not belong to {provider!r} model {model!r}. "
            f"Allowed: {allowed_voices}"
        )


def validate_llm(*, provider: str, model: str) -> None:
    if provider != "openai":
        raise ValidationAppError(
            f"Only the OpenAI LLM provider is supported today, got {provider!r}."
        )
    if model not in OPENAI_LLM_MODELS:
        raise ValidationAppError(f"Unknown LLM model {model!r}. Allowed: {OPENAI_LLM_MODELS}")


def validate_ambient_sound(sound_id: str) -> None:
    allowed = [s["id"] for s in AMBIENT_SOUNDS]
    if sound_id not in allowed:
        raise ValidationAppError(f"Unknown ambient sound {sound_id!r}. Allowed: {allowed}")


def validate_turn_detection_mode(mode: str) -> None:
    if mode not in TURN_DETECTION_MODES:
        raise ValidationAppError(
            f"Unknown turn detection mode {mode!r}. Allowed: {TURN_DETECTION_MODES}"
        )


def build_catalog_response() -> dict:
    """Assembles the full provider/model/voice catalog for
    GET /internal/voice-agents/providers (dict keys are snake_case,
    matching Python convention — the CamelModel response schema in
    schemas/builder.py converts to camelCase for the wire). Never touches
    Settings — contains no secrets, only public model/voice identifiers.
    """
    return {
        "providers": [
            {
                "id": "openai",
                "name": PROVIDER_DISPLAY_NAMES["openai"],
                "capabilities": PROVIDER_CAPABILITIES["openai"],
                "realtime_models": REALTIME_MODELS,
                "realtime_voices": REALTIME_VOICES,
                "stt_models": OPENAI_STT_MODELS,
                "stt_modes": [],
                "tts_models": OPENAI_TTS_MODELS,
                "tts_voices": OPENAI_TTS_VOICES,
                "tts_voices_by_model": {},
                "llm_models": OPENAI_LLM_MODELS,
            },
            {
                "id": "elevenlabs",
                "name": PROVIDER_DISPLAY_NAMES["elevenlabs"],
                "capabilities": PROVIDER_CAPABILITIES["elevenlabs"],
                "realtime_models": [],
                "realtime_voices": [],
                "stt_models": ELEVENLABS_STT_MODELS,
                "stt_modes": [],
                "tts_models": ELEVENLABS_TTS_MODELS,
                "tts_voices": [],
                "tts_voices_by_model": {m: ELEVENLABS_VOICES for m in ELEVENLABS_TTS_MODELS},
                "llm_models": [],
            },
            {
                "id": "sarvam",
                "name": PROVIDER_DISPLAY_NAMES["sarvam"],
                "capabilities": PROVIDER_CAPABILITIES["sarvam"],
                "realtime_models": [],
                "realtime_voices": [],
                "stt_models": SARVAM_STT_MODELS,
                "stt_modes": SARVAM_STT_MODES,
                "tts_models": SARVAM_TTS_MODELS,
                "tts_voices": [],
                "tts_voices_by_model": SARVAM_VOICES,
                "llm_models": [],
            },
        ],
        "turn_detection_modes": TURN_DETECTION_MODES,
        "ambient_sounds": AMBIENT_SOUNDS,
    }
