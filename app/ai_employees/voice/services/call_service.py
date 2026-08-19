from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.ai_employees.voice.models.call import Call, CallDirection, CallStatus
from app.ai_employees.voice.models.call_event import CallEvent
from app.ai_employees.voice.models.recording import Recording, RecordingStatus
from app.ai_employees.voice.models.transcript import Transcript
from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.call_repository import (
    CallEventRepository,
    CallRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.runtime.base import VoiceRuntimeProvider
from app.shared.errors.exceptions import ConflictError, NotFoundError


class CallService:
    def __init__(
        self,
        call_repo: CallRepository,
        event_repo: CallEventRepository,
        transcript_repo: TranscriptRepository,
        recording_repo: RecordingRepository,
        agent_repo: VoiceAgentRepository,
        version_repo: AgentVersionRepository,
        runtime_provider: VoiceRuntimeProvider,
    ) -> None:
        self.call_repo = call_repo
        self.event_repo = event_repo
        self.transcript_repo = transcript_repo
        self.recording_repo = recording_repo
        self.agent_repo = agent_repo
        self.version_repo = version_repo
        self.runtime_provider = runtime_provider

    async def start_call(
        self,
        organization_id: str,
        voice_agent_id: str,
        *,
        direction: CallDirection = CallDirection.INBOUND,
        caller_name: str | None = None,
        caller_number: str | None = None,
        provider_call_id: str | None = None,
    ) -> tuple[Call, str, str]:
        agent = await self.agent_repo.get_by_id(organization_id, voice_agent_id)
        if agent is None:
            raise NotFoundError("Voice agent not found.")

        active_version = await self.version_repo.get_active_published(
            organization_id, voice_agent_id
        )
        if active_version is None:
            raise ConflictError(
                "Cannot initiate call: Voice agent has no active published configuration."
            )

        # Create room via LiveKit runtime provider
        room_name = f"room_{agent.id}_{int(datetime.now(UTC).timestamp())}"
        await self.runtime_provider.create_room(room_name=room_name, metadata=active_version.id)

        participant_identity = caller_name or caller_number or "customer"
        token = self.runtime_provider.generate_access_token(
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=participant_identity,
            metadata=active_version.id,
            ttl_seconds=3600,
        )

        call = Call(
            organization_id=organization_id,
            voice_agent_id=voice_agent_id,
            agent_version_id=active_version.id,
            provider_call_id=provider_call_id,
            room_name=room_name,
            caller_name=caller_name,
            caller_number=caller_number,
            direction=direction,
            status=CallStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
        )
        saved_call = await self.call_repo.add(call)

        # Initialize Transcript record
        transcript = Transcript(
            organization_id=organization_id,
            call_id=saved_call.id,
            turns=[],
        )
        await self.transcript_repo.add(transcript)

        # Dispatch real-time agent worker to the room
        await self.runtime_provider.dispatch_agent(
            room_name=room_name, agent_name="voice_agent", metadata=active_version.id
        )

        return saved_call, room_name, token

    async def end_call(
        self,
        organization_id: str,
        call_id: str,
        *,
        status: CallStatus = CallStatus.COMPLETED,
        duration_seconds: int | None = None,
    ) -> Call:
        call = await self.call_repo.get_by_id(organization_id, call_id)
        if call is None:
            raise NotFoundError("Call not found.")

        now = datetime.now(UTC)
        call.status = status
        call.ended_at = now

        if duration_seconds is not None:
            call.duration_seconds = duration_seconds
        elif call.started_at:
            call.duration_seconds = max(0, int((now - call.started_at).total_seconds()))

        return call

    async def record_event(
        self,
        organization_id: str,
        call_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> CallEvent:
        event = CallEvent(
            organization_id=organization_id,
            call_id=call_id,
            event_type=event_type,
            payload=payload or {},
            occurred_at=datetime.now(UTC),
        )
        return await self.event_repo.add(event)

    async def append_transcript_turn(
        self,
        organization_id: str,
        call_id: str,
        speaker: str,
        text: str,
    ) -> Transcript:
        transcript = await self.transcript_repo.get_by_call_id(organization_id, call_id)
        if transcript is None:
            transcript = Transcript(
                organization_id=organization_id,
                call_id=call_id,
                turns=[],
            )
            transcript = await self.transcript_repo.add(transcript)

        turn = {
            "id": f"turn_{len(transcript.turns) + 1}",
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        turns = list(transcript.turns)
        turns.append(turn)
        transcript.turns = turns
        return transcript

    async def save_recording_metadata(
        self,
        organization_id: str,
        call_id: str,
        storage_key: str,
        duration_seconds: int,
        consent_given: bool = True,
    ) -> Recording:
        recording = await self.recording_repo.get_by_call_id(organization_id, call_id)
        if recording is None:
            recording = Recording(
                organization_id=organization_id,
                call_id=call_id,
                storage_key=storage_key,
                duration_seconds=duration_seconds,
                consent_given=consent_given,
                status=RecordingStatus.AVAILABLE if consent_given else RecordingStatus.FAILED,
            )
            recording = await self.recording_repo.add(recording)
        else:
            recording.storage_key = storage_key
            recording.duration_seconds = duration_seconds
            recording.consent_given = consent_given
            recording.status = (
                RecordingStatus.AVAILABLE if consent_given else RecordingStatus.FAILED
            )

        call = await self.call_repo.get_by_id(organization_id, call_id)
        if call and consent_given:
            call.recording_available = True

        return recording
