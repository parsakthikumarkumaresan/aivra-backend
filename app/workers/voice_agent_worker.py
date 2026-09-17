"""Jaan Voice AI Employee — real-time LiveKit Agents worker process (not
the FastAPI app, not the RQ worker). Conducts the actual phone/browser
conversation, either via OpenAI Realtime speech-to-speech or a Custom
STT -> LLM -> TTS pipeline, per the agent's AgentVersion configuration.

Run with:  python -m app.workers.voice_agent_worker start

Mirrors the proven-working pattern in
app.ai_employees.hr.runtime.screening_agent (a fresh DB engine per
dispatched job, AgentSession.start()'s return is NOT "call over" — the
real end-of-call signal is the session's own "close" event) — HR's own
pipeline is untouched; this is Jaan's independently-scoped equivalent.

API surface confirmed against the installed livekit-agents/livekit-plugins-*
packages via the already-working HR reference implementation, rather than
assumed from docs, for every symbol that file also uses.
"""

from __future__ import annotations

import asyncio

from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, WorkerOptions
from livekit.agents.voice.events import (
    CloseEvent,
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
)
from livekit.plugins import noise_cancellation, openai, silero
from livekit.plugins.openai.realtime import RealtimeModel
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession as DbAsyncSession,
)

from app.ai_employees.voice.models.call import CallStatus
from app.ai_employees.voice.providers.catalog import AMBIENT_SOUNDS
from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.call_repository import (
    CallEventRepository,
    CallRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.runtime import voice_pipeline
from app.ai_employees.voice.schemas.voice_runtime_config import normalize_turn_mode, voice_mode_of
from app.ai_employees.voice.services.call_service import CallService
from app.core.config import get_settings
from app.core.logging import get_logger
from app.knowledge.repositories.document_chunk_repository import DocumentChunkRepository
from app.knowledge.repositories.source_repository import SourceRepository
from app.knowledge.services.retrieval_service import RetrievalService
from app.shared.ai_providers.factory import get_embedding_provider

# Same NoReferencedTableError gotcha screening_agent.py documents for the HR
# process — this is a long-running worker process, not the FastAPI app, so
# SQLAlchemy's declarative metadata is otherwise incomplete here.
from app.shared.database.all_models import Base  # noqa: F401,E402
from app.workers.jobs.voice_jobs import enqueue_post_call_analysis

logger = get_logger(__name__)

SessionFactory = async_sessionmaker[DbAsyncSession]

_AMBIENT_SOUND_CLIPS = {s["id"]: s["clip"] for s in AMBIENT_SOUNDS}


def _new_engine_and_session_factory() -> tuple[AsyncEngine, SessionFactory]:
    """A fresh engine/session-maker scoped to a single entrypoint() call —
    see app.ai_employees.hr.runtime.screening_agent's identical helper for
    why the shared cached engine must not be reused across dispatched jobs
    in a long-running Agents worker process.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine, session_factory


def _call_service(session: DbAsyncSession) -> CallService:
    from app.ai_employees.voice.runtime.factory import get_voice_runtime_provider

    return CallService(
        CallRepository(session),
        CallEventRepository(session),
        TranscriptRepository(session),
        RecordingRepository(session),
        VoiceAgentRepository(session),
        AgentVersionRepository(session),
        get_voice_runtime_provider(),
    )


async def _append_transcript_turn(
    session_factory: SessionFactory, organization_id: str, call_id: str, *, speaker: str, text: str
) -> None:
    if not text.strip():
        return
    async with session_factory() as session:
        await _call_service(session).append_transcript_turn(organization_id, call_id, speaker, text)
        await session.commit()


def _log_background_task_failure(task: asyncio.Task, *, call_id: str) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "TRANSCRIPT_WRITE_FAILED", call_id=call_id, error=f"{type(exc).__name__}: {exc}"
        )


async def _finalize_call(
    session_factory: SessionFactory, organization_id: str, call_id: str, *, failed: bool
) -> None:
    async with session_factory() as session:
        await _call_service(session).end_call(
            organization_id, call_id, status=CallStatus.FAILED if failed else CallStatus.COMPLETED
        )
        await session.commit()
    if not failed:
        enqueue_post_call_analysis(organization_id, call_id)
    logger.info("VOICE_CALL_ENDED", call_id=call_id, failed=failed)


def _build_ambient_audio_player(voice_config: dict) -> object | None:
    """Constructs a real livekit.agents BackgroundAudioPlayer from
    voice_config.backgroundSoundId/backgroundSoundVolume, or returns None
    if ambient sound is off/unconfigured. Import is deferred and
    defensively wrapped: if the installed livekit-agents version doesn't
    expose this exact API surface, ambient sound is honestly disabled
    (never silently faked) rather than crashing call setup.
    """
    if not voice_config.get("backgroundSound"):
        return None
    sound_id = voice_config.get("backgroundSoundId")
    clip_name = _AMBIENT_SOUND_CLIPS.get(sound_id) if sound_id else None
    if not clip_name:
        return None
    volume = float(voice_config.get("backgroundSoundVolume", 0.3))
    try:
        # Verified import path against the installed livekit-agents package
        # (livekit.agents.voice's own __init__ does not re-export these —
        # they live in the background_audio submodule).
        from livekit.agents.voice.background_audio import (
            AudioConfig,
            BackgroundAudioPlayer,
            BuiltinAudioClip,
        )

        clip = getattr(BuiltinAudioClip, clip_name, None)
        if clip is None:
            logger.warning("AMBIENT_SOUND_CLIP_UNAVAILABLE", clip=clip_name)
            return None
        return BackgroundAudioPlayer(ambient_sound=AudioConfig(clip, volume=volume))
    except Exception:
        logger.exception("AMBIENT_SOUND_UNAVAILABLE_FOR_THIS_RUNTIME")
        return None


def _build_session(
    voice_config: dict, transcription_config: dict, advanced_config: dict
) -> AgentSession:
    """Instantiates the real AgentSession for either Realtime or Custom
    STT/TTS/LLM mode, per the agent's normalized configuration. This is the
    fix for the audit finding that AgentSession was constructed with only
    an LLM and never attached STT/TTS/turn-detection.
    """
    settings = get_settings()
    mode = voice_mode_of(voice_config)

    if mode == "realtime":
        model = voice_config.get("realtimeModel") or settings.voice_realtime_model
        voice = voice_config.get("realtimeVoice", "marin")
        realtime_model: RealtimeModel = voice_pipeline.build_realtime_model(
            provider="openai", model=model, voice=voice, settings=settings
        )
        return AgentSession(llm=realtime_model)

    # Custom STT + LLM + TTS.
    language = voice_config.get("language")
    stt_provider = transcription_config.get("provider", "openai")
    stt_model = transcription_config.get(
        "model", "gpt-4o-transcribe" if stt_provider == "openai" else ""
    )
    tts_provider = voice_config.get("provider", "openai")
    tts_model = voice_config.get("model", "gpt-4o-mini-tts" if tts_provider == "openai" else "")
    tts_voice = voice_config.get("voiceName", "alloy")
    llm_model = advanced_config.get("llmModel") or settings.voice_llm_model

    stt = voice_pipeline.build_stt(
        provider=stt_provider, model=stt_model, language=language, settings=settings
    )
    tts = voice_pipeline.build_tts(
        provider=tts_provider,
        model=tts_model,
        voice_id=tts_voice,
        language=language,
        settings=settings,
    )
    llm = openai.LLM(model=llm_model, api_key=settings.openai_api_key.get_secret_value())
    vad = silero.VAD.load()

    turn_mode = normalize_turn_mode(transcription_config.get("turnMode", "Heuristic"))
    turn_detection: object = "vad"
    min_endpointing_delay = 0.5
    if turn_mode == "semantic":
        try:
            # livekit-plugins-turn-detector is deprecated in favor of
            # livekit.agents.inference.TurnDetector (which requires
            # separate LiveKit Cloud inference credentials/billing) — kept
            # on the local, credential-free model for now since it still
            # works (verified against the installed package: emits a
            # DeprecationWarning, not an error).
            from livekit.plugins.turn_detector.multilingual import MultilingualModel

            turn_detection = MultilingualModel()
        except Exception:
            logger.exception("SEMANTIC_TURN_DETECTOR_UNAVAILABLE_FALLING_BACK_TO_VAD")
            turn_detection = "vad"
    elif turn_mode == "fixed_silence":
        min_endpointing_delay = float(transcription_config.get("fixedSilenceSeconds", 1.0))
    # "heuristic" -> plain VAD-based endpointing at LiveKit's default delay.

    return AgentSession(
        llm=llm,
        stt=stt,
        tts=tts,
        vad=vad,
        turn_detection=turn_detection,
        min_endpointing_delay=min_endpointing_delay,
    )


async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"Connecting to LiveKit room: {ctx.room.name}")
    await ctx.connect()

    engine, session_factory = _new_engine_and_session_factory()
    try:
        # The Call row already exists (created by CallService.start_call
        # before this worker was dispatched) — look it up by room_name to
        # get its real organization_id, rather than the previous fragile
        # "parse it out of the room name string" approach.
        async with session_factory() as session:
            call = await CallRepository(session).get_by_room_name(ctx.room.name)

        if call is None:
            logger.error("VOICE_CALL_NOT_FOUND_FOR_ROOM", room_name=ctx.room.name)
            return

        organization_id = call.organization_id
        call_id = call.id

        async with session_factory() as session:
            version_repo = AgentVersionRepository(session)
            agent_version = await version_repo.get_by_id(organization_id, call.agent_version_id)

        if agent_version is None:
            logger.error("AGENT_VERSION_NOT_FOUND", call_id=call_id)
            await _finalize_call(session_factory, organization_id, call_id, failed=True)
            return

        system_prompt = agent_version.prompt_config.get(
            "systemPrompt", "You are a professional AI Voice Employee powered by AIVRA."
        )
        knowledge_ids: list[str] = agent_version.library.get("knowledgeSourceIds", [])

        # RAG knowledge grounding (unchanged logic, now using the real
        # organization_id resolved above instead of parsing the room name).
        if knowledge_ids:
            async with session_factory() as session:
                retrieval_service = RetrievalService(
                    SourceRepository(session),
                    DocumentChunkRepository(session),
                    get_embedding_provider(),
                )
                chunks = await retrieval_service.retrieve(
                    organization_id=organization_id,
                    employee_type="voice",
                    query=system_prompt,
                    limit=3,
                )
                if chunks:
                    system_prompt += "\n\nKNOWLEDGE CONTEXT:\n" + "\n".join(
                        c.content for c in chunks
                    )

        try:
            agent_session = _build_session(
                agent_version.voice_config,
                agent_version.transcription_config,
                agent_version.advanced_config,
            )
        except Exception:
            logger.exception("VOICE_SESSION_BUILD_FAILED", call_id=call_id)
            await _finalize_call(session_factory, organization_id, call_id, failed=True)
            return

        agent = Agent(instructions=system_prompt)

        pending_writes: list[asyncio.Task] = []

        def _track(task: asyncio.Task) -> None:
            pending_writes.append(task)
            task.add_done_callback(lambda t: _log_background_task_failure(t, call_id=call_id))
            task.add_done_callback(
                lambda t: pending_writes.remove(t) if t in pending_writes else None
            )

        def _on_conversation_item(event: ConversationItemAddedEvent) -> None:
            text = getattr(event.item, "text_content", None)
            role = getattr(event.item, "role", None)
            if text:
                _track(
                    asyncio.create_task(
                        _append_transcript_turn(
                            session_factory,
                            organization_id,
                            call_id,
                            speaker=str(role or "agent"),
                            text=text,
                        )
                    )
                )

        def _on_user_transcribed(event: UserInputTranscribedEvent) -> None:
            if event.transcript and event.is_final:
                _track(
                    asyncio.create_task(
                        _append_transcript_turn(
                            session_factory,
                            organization_id,
                            call_id,
                            speaker="customer",
                            text=event.transcript,
                        )
                    )
                )

        closed = asyncio.Event()
        close_event_holder: dict[str, CloseEvent] = {}

        def _on_close(event: CloseEvent) -> None:
            close_event_holder["event"] = event
            closed.set()

        agent_session.on("conversation_item_added", _on_conversation_item)
        agent_session.on("user_input_transcribed", _on_user_transcribed)
        agent_session.on("close", _on_close)

        try:
            # AgentSession.start()'s return is NOT "call over" (see HR's
            # identical comment in screening_agent.py) — the real
            # end-of-call signal is the session's own "close" event, waited
            # on below.
            await agent_session.start(
                agent,
                room=ctx.room,
                room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
            )
        except Exception:
            logger.exception("VOICE_SESSION_START_FAILED", call_id=call_id)
            await _finalize_call(session_factory, organization_id, call_id, failed=True)
            return

        background_audio = _build_ambient_audio_player(agent_version.voice_config)
        if background_audio is not None:
            try:
                await background_audio.start(room=ctx.room, agent_session=agent_session)
            except Exception:
                logger.exception("AMBIENT_SOUND_START_FAILED", call_id=call_id)

        logger.info("VOICE_CALL_ACTIVE", call_id=call_id, room_name=ctx.room.name)
        await closed.wait()
        if pending_writes:
            await asyncio.gather(*pending_writes, return_exceptions=True)

        close_event = close_event_holder.get("event")
        failed = close_event is not None and close_event.reason.value == "error"
        await _finalize_call(session_factory, organization_id, call_id, failed=failed)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="voice_agent",
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key.get_secret_value(),
            api_secret=settings.livekit_api_secret.get_secret_value(),
        )
    )


if __name__ == "__main__":
    main()
