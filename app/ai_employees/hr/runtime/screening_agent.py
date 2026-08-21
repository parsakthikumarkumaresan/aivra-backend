"""AIVRA HR AI Voice Screening agent — a separate, long-running LiveKit
Agents worker process (not the FastAPI app, not the RQ worker). Conducts
the actual phone conversation via OpenAI Realtime speech-to-speech, using
the official LiveKit OpenAI plugin (no separate STT->LLM->TTS pipeline).

Run with:  python -m app.ai_employees.hr.runtime.screening_agent start

Independently scoped from app.ai_employees.voice — never imports Voice
models, prompts, or runtime code (spec: HR/Voice bounded-context
isolation). The only content that reaches the model is
``Screening.prompt_text`` exactly as HR reviewed/edited it — no additional
system prompt is layered on top that could leak internal instructions.

API surface confirmed against the installed livekit-agents==1.6.10 and
livekit-plugins-openai packages (AgentSession/Agent/JobContext/WorkerOptions,
the "conversation_item_added"/"user_input_transcribed" event names, and
livekit.plugins.openai.realtime.RealtimeModel) rather than assumed from docs.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, WorkerOptions
from livekit.agents.voice.events import (
    CloseEvent,
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
)
from livekit.plugins import noise_cancellation
from livekit.plugins.openai.realtime import RealtimeModel
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.ai_employees.hr.models.screening import ScreeningStatus
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.core.config import get_settings
from app.core.logging import get_logger

# This process only ever directly imports the Screening model, so
# SQLAlchemy's declarative metadata is otherwise incomplete here — a flush
# on Screening (e.g. appending a transcript turn) then fails with
# NoReferencedTableError because Organization was never registered (same
# root cause app.workers.worker fixed for the RQ worker process; see that
# module's docstring). Importing the full model registry here guarantees
# every DB write in this process has complete metadata regardless of which
# job runs. Critical: without this, transcript-turn writes fail silently
# (they run via asyncio.create_task, so the failure was never surfaced)
# and a real, connected, minutes-long call would end with no transcript.
from app.shared.database.all_models import Base  # noqa: F401,E402
from app.workers.jobs.hr_screening_result_jobs import enqueue_screening_result

logger = get_logger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]


def _new_engine_and_session_factory() -> tuple[AsyncEngine, SessionFactory]:
    """A fresh engine/session-maker, scoped to a single entrypoint() call.

    Deliberately NOT app.shared.database.session's cached module-level
    engine: that cache is safe for the FastAPI app (one event loop for the
    process lifetime) and RQ jobs (one asyncio.run() per job, engine
    disposed in a finally), but this agent process is long-running and
    livekit-agents executes each dispatched job on its own runner/event
    loop. Reusing a cached engine across those loops causes
    "Future attached to a different loop" errors on the second and later
    calls — a fresh engine per call, disposed at the end, avoids that
    entirely regardless of the framework's threading/loop model.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine, session_factory


async def _append_transcript_turn(
    session_factory: SessionFactory,
    organization_id: str,
    screening_id: str,
    *,
    speaker: str,
    text: str,
    is_final: bool,
) -> None:
    if not text.strip():
        return
    async with session_factory() as session:
        repo = ScreeningRepository(session)
        screening = await repo.get_by_id(organization_id, screening_id)
        if screening is None:
            return
        turns = list(screening.transcript or [])
        turns.append(
            {
                "speaker": speaker,
                "text": text,
                "isFinal": is_final,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        screening.transcript = turns
        await session.commit()
    logger.info(
        "TRANSCRIPT_UPDATED", screening_id=screening_id, speaker=speaker, turn_count=len(turns)
    )


def _log_background_task_failure(task: asyncio.Task, *, screening_id: str) -> None:
    """asyncio.create_task fire-and-forget calls swallow exceptions unless a
    done-callback observes them — this is what surfaced the previous
    NoReferencedTableError instead of it vanishing as "Task exception was
    never retrieved" (spec: never let a persistence failure go silent).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "TRANSCRIPT_WRITE_FAILED",
            screening_id=screening_id,
            error=f"{type(exc).__name__}: {exc}",
        )


async def _finalize_screening(
    session_factory: SessionFactory,
    organization_id: str,
    screening_id: str,
    *,
    failure_reason: str | None,
) -> None:
    async with session_factory() as session:
        repo = ScreeningRepository(session)
        screening = await repo.get_by_id(organization_id, screening_id)
        if screening is None:
            return
        if failure_reason:
            screening.status = ScreeningStatus.FAILED
            screening.failure_reason = failure_reason
        await session.commit()

    if failure_reason:
        logger.error(
            "SCREENING_CALL_FAILED", screening_id=screening_id, stage="agent", reason=failure_reason
        )
    else:
        logger.info("TRANSCRIPT_FINALIZED", screening_id=screening_id)
        enqueue_screening_result(organization_id=organization_id, screening_id=screening_id)
        logger.info("SCREENING_COMPLETED", screening_id=screening_id)


async def entrypoint(ctx: JobContext) -> None:
    metadata = json.loads(ctx.job.metadata or "{}")
    organization_id = metadata.get("organizationId")
    screening_id = metadata.get("screeningId")
    if not organization_id or not screening_id:
        logger.error("screening_agent_missing_metadata", metadata=ctx.job.metadata)
        return

    logger.info("AGENT_STARTED", screening_id=screening_id, room_name=ctx.room.name)
    settings = get_settings()

    # One engine per dispatched job, disposed at the end of this call — see
    # _new_engine_and_session_factory's docstring for why the shared cached
    # engine (app.shared.database.session) must not be used here.
    engine, session_factory = _new_engine_and_session_factory()
    try:
        async with session_factory() as session:
            screening = await ScreeningRepository(session).get_by_id(organization_id, screening_id)
            prompt_text = screening.prompt_text if screening else None

        prompt_text = (prompt_text or "").strip()
        if not prompt_text:
            logger.error("screening_agent_blank_prompt", screening_id=screening_id)
            await _finalize_screening(
                session_factory,
                organization_id,
                screening_id,
                failure_reason="Screening prompt was blank at call time — refusing to start "
                "a conversation with no real, HR-reviewed instructions.",
            )
            return

        await ctx.connect()
        logger.info("CALL_CONNECTED", screening_id=screening_id, room_name=ctx.room.name)

        try:
            agent = Agent(instructions=prompt_text)
            realtime_model = RealtimeModel(
                model=settings.hr_screening_realtime_model,
                voice=settings.hr_screening_voice,
                api_key=settings.openai_api_key.get_secret_value(),
            )
            agent_session: AgentSession = AgentSession(llm=realtime_model)
        except Exception as exc:
            # Distinct from a SIP/dispatch failure (handled upstream in
            # hr_screening_jobs.py) — the call connected fine, but the
            # OpenAI Realtime session itself could not be constructed (bad
            # API key, unsupported model/voice, plugin error).
            logger.exception("AGENT_REALTIME_FAILED", screening_id=screening_id)
            await _finalize_screening(
                session_factory,
                organization_id,
                screening_id,
                failure_reason=f"OpenAI Realtime agent failed to start: {exc}",
            )
            return

        pending_writes: list[asyncio.Task] = []

        def _track(task: asyncio.Task) -> None:
            pending_writes.append(task)
            task.add_done_callback(
                lambda t: _log_background_task_failure(t, screening_id=screening_id)
            )
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
                            screening_id,
                            speaker=str(role or "assistant"),
                            text=text,
                            is_final=True,
                        )
                    )
                )

        def _on_user_transcribed(event: UserInputTranscribedEvent) -> None:
            if event.transcript:
                _track(
                    asyncio.create_task(
                        _append_transcript_turn(
                            session_factory,
                            organization_id,
                            screening_id,
                            speaker="candidate",
                            text=event.transcript,
                            is_final=event.is_final,
                        )
                    )
                )

        # AgentSession.start() only starts the session/RoomIO — it returns
        # once setup completes, NOT when the call ends (confirmed against
        # the installed SDK: its own docstring is "Start the voice agent").
        # Treating start()'s return as "call over" was the bug: the real
        # conversation continued for another ~90s after start() returned,
        # so finalizing there enqueued result-generation against an empty
        # transcript that hadn't been written yet. The actual end-of-call
        # signal is the session's own "close" event.
        closed = asyncio.Event()
        close_event_holder: dict[str, CloseEvent] = {}

        def _on_close(event: CloseEvent) -> None:
            close_event_holder["event"] = event
            closed.set()

        agent_session.on("conversation_item_added", _on_conversation_item)
        agent_session.on("user_input_transcribed", _on_user_transcribed)
        agent_session.on("close", _on_close)

        try:
            await agent_session.start(
                agent,
                room=ctx.room,
                # Agent-side noise cancellation (LiveKit's recommended
                # placement over SIP-trunk-side NC — it unlocks the enhanced
                # Krisp models). BVCTelephony is the narrowband (8kHz) model
                # tuned for phone-call audio, matching this SIP participant's
                # source, rather than BVC which targets full-band WebRTC mic
                # audio: https://docs.livekit.io/transport/media/noise-cancellation/
                room_input_options=RoomInputOptions(
                    noise_cancellation=noise_cancellation.BVCTelephony()
                ),
            )
        except Exception as exc:
            logger.exception("AGENT_REALTIME_FAILED", screening_id=screening_id)
            await _finalize_screening(
                session_factory,
                organization_id,
                screening_id,
                failure_reason=f"OpenAI Realtime agent failed to start: {exc}",
            )
            return

        # max_call_duration (LiveKit SIP participant, see
        # livekit_screening_provider.py) is the ultimate safety net — this
        # wait has no separate timeout of its own.
        await closed.wait()
        # Let any transcript-turn writes still in flight at the moment of
        # close finish committing before generating the result.
        if pending_writes:
            await asyncio.gather(*pending_writes, return_exceptions=True)

        close_event = close_event_holder.get("event")
        if close_event is not None and close_event.reason.value == "error":
            logger.error(
                "AGENT_REALTIME_FAILED", screening_id=screening_id, error=str(close_event.error)
            )
            await _finalize_screening(
                session_factory,
                organization_id,
                screening_id,
                failure_reason=f"OpenAI Realtime session ended with an error: {close_event.error}",
            )
            return

        logger.info(
            "CALL_ENDED",
            screening_id=screening_id,
            room_name=ctx.room.name,
            reason=close_event.reason.value if close_event else "unknown",
        )
        await _finalize_screening(
            session_factory, organization_id, screening_id, failure_reason=None
        )
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=settings.hr_screening_agent_name,
            ws_url=settings.hr_livekit_url,
            api_key=settings.hr_livekit_api_key.get_secret_value(),
            api_secret=settings.hr_livekit_api_secret.get_secret_value(),
        )
    )


if __name__ == "__main__":
    main()
