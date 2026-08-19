from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.call_repository import (
    CallEventRepository,
    CallRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.runtime.factory import get_voice_runtime_provider
from app.ai_employees.voice.services.call_service import CallService
from app.shared.database.session import get_db
from app.workers.jobs.voice_jobs import enqueue_post_call_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/voice/webhooks", tags=["Voice Webhooks"])


@router.post("/livekit")
async def livekit_webhook(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    raw_body = await request.body()
    runtime_provider = get_voice_runtime_provider()

    runtime_event = runtime_provider.verify_webhook(
        body=raw_body.decode("utf-8", errors="ignore"),
        auth_header=authorization or "",
    )

    event_data = await request.json()
    event_id = event_data.get("id")
    event_name = runtime_event.event_type or event_data.get("event")
    room_name = (
        runtime_event.room_name
        or event_data.get("room", {}).get("name")
        or event_data.get("egressInfo", {}).get("roomName")
    )

    if not event_name or not room_name:
        return {"status": "ignored", "reason": "missing_event_or_room"}

    call_repo = CallRepository(db)
    event_repo = CallEventRepository(db)
    transcript_repo = TranscriptRepository(db)
    recording_repo = RecordingRepository(db)
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)

    call_service = CallService(
        call_repo,
        event_repo,
        transcript_repo,
        recording_repo,
        agent_repo,
        version_repo,
        runtime_provider,
    )

    call = await call_repo.get_by_room_name(room_name)
    if call is None:
        logger.warning(f"LiveKit webhook for unknown room: {room_name}")
        return {"status": "ignored", "reason": "unknown_room"}

    # Idempotency check via event_id
    if event_id:
        existing_event = await event_repo.get_by_event_type_and_timestamp(
            call.organization_id, call.id, event_name, str(event_id)
        )
        if existing_event is not None:
            return {"status": "already_processed", "event_id": event_id}

    # Record event
    await call_service.record_event(
        call.organization_id, call.id, event_name, payload={"event_id": event_id, **event_data}
    )

    # Process event type
    if event_name in ("room_finished", "participant_left"):
        await call_service.end_call(call.organization_id, call.id)
        # Enqueue post-call analysis background job
        enqueue_post_call_analysis(call.organization_id, call.id)

    elif event_name in ("egress_ended", "track_published"):
        egress_info = event_data.get("egressInfo", {})
        file_results = egress_info.get("fileResults", [])
        if file_results:
            storage_key = file_results[0].get("filename", f"recordings/{call.id}.mp4")
            duration = int(egress_info.get("duration", 0))
            await call_service.save_recording_metadata(
                call.organization_id, call.id, storage_key=storage_key, duration_seconds=duration
            )

    return {"status": "processed", "event": event_name, "call_id": call.id}
