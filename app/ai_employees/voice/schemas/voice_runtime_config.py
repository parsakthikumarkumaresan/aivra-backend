"""Server-side validation for the normalized voice-runtime fields inside
Jaan's existing freeform JSON config columns (``voice_config``,
``transcription_config``, ``advanced_config`` on AgentVersion).

This does NOT change the database schema — it validates specific keys
within those JSON blobs before they're persisted, matching
app.ai_employees.voice.models.agent_version's own documented design ("each
section's internal shape is UI-owned config, not something the backend
needs to query into"). Validation is additive: any key not covered here is
left untouched, so existing/legacy config data never fails validation.

Normalized fields introduced by this module:

  voice_config:
    mode: "realtime" | "custom"                 (default "custom")
    realtimeProvider / realtimeModel / realtimeVoice   (mode == "realtime")
    provider / model / voiceName                       (mode == "custom", TTS)
    backgroundSound: bool, backgroundSoundId, backgroundSoundVolume (0-1)

  transcription_config:
    provider / model                              (mode == "custom", STT)
    turnMode: "Heuristic" | "Semantic" | "Fixed Silence"
    fixedSilenceSeconds: float                    (only when turnMode == "Fixed Silence")

  advanced_config:
    llmProvider / llmModel                        (llmProvider must be "OpenAI" today)
"""

from __future__ import annotations

from app.ai_employees.voice.providers import catalog
from app.shared.errors.exceptions import ValidationAppError

VOICE_MODES = ("realtime", "custom")

_TURN_MODE_LABELS = {
    "Heuristic": "heuristic",
    "Semantic": "semantic",
    "Fixed Silence": "fixed_silence",
}


def normalize_turn_mode(label: str) -> str:
    return _TURN_MODE_LABELS.get(label, label.lower().replace(" ", "_"))


def normalize_llm_provider(label: str) -> str:
    return label.lower()


def voice_mode_of(voice_config: dict) -> str:
    return voice_config.get("mode", "custom")


def validate_voice_config(voice_config: dict) -> None:
    mode = voice_mode_of(voice_config)
    if mode not in VOICE_MODES:
        raise ValidationAppError(f"voiceConfig.mode must be one of {VOICE_MODES}, got {mode!r}.")

    if mode == "realtime":
        catalog.validate_realtime(
            provider=voice_config.get("realtimeProvider", "openai"),
            model=voice_config.get("realtimeModel", catalog.REALTIME_MODELS[0]),
            voice=voice_config.get("realtimeVoice", catalog.REALTIME_VOICES[0]["id"]),
        )
    else:
        provider = voice_config.get("provider")
        model = voice_config.get("model")
        voice_name = voice_config.get("voiceName")
        if provider and model and voice_name:
            catalog.validate_tts(provider=provider, model=model, voice_id=voice_name)

    if voice_config.get("backgroundSound"):
        sound_id = voice_config.get("backgroundSoundId")
        if sound_id:
            catalog.validate_ambient_sound(sound_id)
        volume = voice_config.get("backgroundSoundVolume")
        if volume is not None and not (0.0 <= float(volume) <= 1.0):
            raise ValidationAppError(
                "voiceConfig.backgroundSoundVolume must be between 0.0 and 1.0."
            )


def validate_transcription_config(transcription_config: dict, *, voice_mode: str) -> None:
    turn_mode_label = transcription_config.get("turnMode")
    if turn_mode_label:
        normalized = normalize_turn_mode(turn_mode_label)
        catalog.validate_turn_detection_mode(normalized)
        if normalized == "fixed_silence":
            seconds = transcription_config.get("fixedSilenceSeconds", 1.0)
            if not (0.1 <= float(seconds) <= 10.0):
                raise ValidationAppError(
                    "transcriptionConfig.fixedSilenceSeconds must be between 0.1 and 10.0 seconds."
                )

    if voice_mode == "custom":
        provider = transcription_config.get("provider")
        model = transcription_config.get("model")
        if provider and model:
            catalog.validate_stt(provider=provider, model=model)


def validate_advanced_config(advanced_config: dict) -> None:
    provider = advanced_config.get("llmProvider")
    model = advanced_config.get("llmModel")
    if provider and model:
        catalog.validate_llm(provider=normalize_llm_provider(provider), model=model)


def validate_agent_version_config(
    *, voice_config: dict, transcription_config: dict, advanced_config: dict
) -> None:
    """Single entry point called from VoiceAgentService.update_draft after a
    patch is merged — validates the full merged state so a change to one
    section (e.g. switching voiceConfig.mode to "realtime") is checked
    against the current state of the others.
    """
    validate_voice_config(voice_config)
    validate_transcription_config(transcription_config, voice_mode=voice_mode_of(voice_config))
    validate_advanced_config(advanced_config)
