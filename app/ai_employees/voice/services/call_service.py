from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

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
from app.ai_employees.voice.services.credit_ledger_service import CreditLedgerService
from app.core.config import get_settings
from app.shared.errors.exceptions import ConflictError, NotFoundError

logger = structlog.get_logger(__name__)


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
        credit_ledger_service: CreditLedgerService,
    ) -> None:
        self.call_repo = call_repo
        self.event_repo = event_repo
        self.transcript_repo = transcript_repo
        self.recording_repo = recording_repo
        self.agent_repo = agent_repo
        self.version_repo = version_repo
        self.runtime_provider = runtime_provider
        self.credit_ledger_service = credit_ledger_service

    async def start_call(
        self,
        organization_id: str,
        voice_agent_id: str,
        *,
        direction: CallDirection = CallDirection.INBOUND,
        caller_name: str | None = None,
        caller_number: str | None = None,
        agent_number: str | None = None,
        provider_call_id: str | None = None,
        use_draft: bool = False,
    ) -> tuple[Call, str, str, str | None]:
        # Call admission gate (Phase 4 spec section 6) — checked before any
        # LiveKit room/dispatch work so an org with no Jaan Voice Credits
        # left never has a real room created for nothing. Raises
        # InsufficientCreditsError (402) if the balance is below the
        # configured minimum; an already-admitted call is never
        # interrupted mid-call for running low afterwards.
        await self.credit_ledger_service.assert_can_start_call(
            organization_id, minimum_balance=get_settings().voice_min_balance_minutes_to_start_call
        )

        agent = await self.agent_repo.get_by_id(organization_id, voice_agent_id)
        if agent is None:
            raise NotFoundError("Voice agent not found.")

        target_version = None
        if use_draft:
            target_version = await self.version_repo.get_draft(organization_id, voice_agent_id)

        if target_version is None:
            target_version = await self.version_repo.get_active_published(
                organization_id, voice_agent_id
            )

        if target_version is None and use_draft:
            # Fallback to any latest draft version
            target_version = await self.version_repo.get_draft(organization_id, voice_agent_id)

        if target_version is None:
            raise ConflictError(
                "Cannot initiate call: Voice agent has no active published configuration."
            )

        # Create room via LiveKit runtime provider
        room_name = f"room_{agent.id}_{int(datetime.now(UTC).timestamp())}"
        await self.runtime_provider.create_room(room_name=room_name, metadata=target_version.id)

        participant_identity = caller_name or caller_number or "customer"
        token = self.runtime_provider.generate_access_token(
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=participant_identity,
            metadata=target_version.id,
            ttl_seconds=3600,
        )

        # If an outbound destination phone number was provided, originate a
        # real SIP participant call. `sip_dial_error` is the honest signal
        # the caller (start_test_call) needs to report a truthful
        # dial_status — a destination number being *requested* is not the
        # same as a real outbound call being *placed*, and reporting
        # "initiated" from request shape alone (the previous bug here) told
        # users a phone was ringing when no real SIP dial had succeeded.
        sip_dial_error: str | None = None
        if caller_number and hasattr(self.runtime_provider, "create_sip_participant"):
            try:
                sip_call_id = await self.runtime_provider.create_sip_participant(
                    room_name=room_name,
                    phone_number=caller_number,
                    caller_id=agent_number,
                )
                if sip_call_id:
                    provider_call_id = sip_call_id
                else:
                    sip_dial_error = (
                        "No SIP trunk is configured for outbound dialing " "(VOICE_SIP_TRUNK_ID)."
                    )
            except Exception as exc:
                logger.warning(
                    "SIP_PARTICIPANT_DIAL_FAILED",
                    agent_id=voice_agent_id,
                    caller_number=caller_number,
                    error=str(exc),
                )
                sip_dial_error = str(exc)

        call = Call(
            organization_id=organization_id,
            voice_agent_id=voice_agent_id,
            agent_version_id=target_version.id,
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
        try:
            await self.runtime_provider.dispatch_agent(
                room_name=room_name, agent_name="voice_agent", metadata=target_version.id
            )
        except Exception as exc:
            logger.warning("AGENT_DISPATCH_FAILED", agent_id=voice_agent_id, error=str(exc))

        return saved_call, room_name, token, sip_dial_error

    async def end_call(
        self,
        organization_id: str,
        call_id: str,
        *,
        status: CallStatus = CallStatus.COMPLETED,
        duration_seconds: int | None = None,
        end_reason: str | None = None,
    ) -> Call:
        call = await self.call_repo.get_by_id(organization_id, call_id)
        if call is None:
            raise NotFoundError("Call not found.")

        now = datetime.now(UTC)
        call.status = status
        call.ended_at = now
        if end_reason is not None:
            call.end_reason = end_reason

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
