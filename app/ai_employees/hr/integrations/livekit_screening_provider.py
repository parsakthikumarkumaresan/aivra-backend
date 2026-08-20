"""HR's own LiveKit/SIP adapter for AI voice screening calls.

Independently scoped from app.ai_employees.voice.runtime.livekit_provider —
same physical LiveKit/SIP account may be reused (see settings.hr_livekit_*),
but this module owns its own client, its own settings, and is never
imported by (or importing from) the Voice bounded context (spec: HR/Voice
isolation).

API surface confirmed against the installed livekit-api==1.2.0 package
(LiveKitAPI().room / .sip / .agent_dispatch) rather than assumed from docs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from livekit import api as lk_api

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LiveKitScreeningConfigurationError(Exception):
    """Raised when HR's LiveKit/SIP settings are missing — must propagate as
    a real failure (spec: never place a fake/simulated call).
    """


class SipParticipantError(Exception):
    """Raised specifically when the SIP-participant (outbound dial) request
    is rejected by LiveKit/the SIP trunk — kept distinct from room-creation
    or agent-dispatch failures so the caller can tell exactly which stage of
    the call-placement chain failed, instead of one generic error.
    """


@dataclass
class DispatchedCall:
    room_name: str
    dispatch_id: str
    sip_participant_identity: str


# The target screening is ~5 minutes, ended naturally by the agent once
# required information is collected (spec section 13) — this is a
# protective ceiling only, never the normal way a call ends.
_MAX_CALL_DURATION = timedelta(minutes=15)


def _client() -> lk_api.LiveKitAPI:
    settings = get_settings()
    if not (settings.hr_livekit_url and settings.hr_livekit_api_key.get_secret_value()):
        raise LiveKitScreeningConfigurationError(
            "HR_LIVEKIT_URL/HR_LIVEKIT_API_KEY/HR_LIVEKIT_API_SECRET are not configured — "
            "cannot place a screening call."
        )
    return lk_api.LiveKitAPI(
        settings.hr_livekit_url,
        settings.hr_livekit_api_key.get_secret_value(),
        settings.hr_livekit_api_secret.get_secret_value(),
    )


async def place_screening_call(
    *, room_name: str, screening_id: str, organization_id: str, phone_number: str
) -> DispatchedCall:
    """Creates the room, dispatches the HR screening agent into it, then
    dials the candidate as an outbound SIP participant. Dispatching the
    agent before dialing means it's already listening when the candidate
    answers, rather than racing to join after pickup.
    """
    settings = get_settings()
    if not settings.hr_sip_trunk_id:
        raise LiveKitScreeningConfigurationError(
            "HR_SIP_TRUNK_ID is not configured — cannot place a screening call."
        )

    client = _client()
    try:
        await client.room.create_room(lk_api.CreateRoomRequest(name=room_name))
        logger.info("LIVEKIT_ROOM_CREATED", screening_id=screening_id, room_name=room_name)

        try:
            dispatch = await client.agent_dispatch.create_dispatch(
                lk_api.CreateAgentDispatchRequest(
                    agent_name=settings.hr_screening_agent_name,
                    room=room_name,
                    # Only IDs in metadata — the agent process fetches the
                    # prompt itself via its own DB session (spec: no
                    # secrets/internal prompts pass through provider-visible
                    # metadata besides IDs needed to look them up).
                    metadata=json.dumps(
                        {"organizationId": organization_id, "screeningId": screening_id}
                    ),
                )
            )
        except lk_api.TwirpError as exc:
            logger.error(
                "AGENT_DISPATCH_FAILED",
                screening_id=screening_id,
                room_name=room_name,
                agent_name=settings.hr_screening_agent_name,
                provider_error_code=exc.code,
                provider_status=exc.status,
            )
            raise
        logger.info(
            "AGENT_DISPATCH_REQUESTED",
            screening_id=screening_id,
            room_name=room_name,
            dispatch_id=dispatch.id,
            agent_name=settings.hr_screening_agent_name,
        )

        participant_identity = f"candidate-{screening_id}"
        logger.info(
            "SIP_PARTICIPANT_REQUESTED",
            screening_id=screening_id,
            room_name=room_name,
            sip_trunk_id=settings.hr_sip_trunk_id,
            participant_identity=participant_identity,
        )
        try:
            sip_participant = await client.sip.create_sip_participant(
                lk_api.CreateSIPParticipantRequest(
                    sip_trunk_id=settings.hr_sip_trunk_id,
                    sip_call_to=phone_number,
                    # Optional outbound caller-ID override — if unset, the
                    # SIP trunk's own configured caller ID is used instead.
                    sip_number=settings.hr_screening_phone_number,
                    room_name=room_name,
                    participant_identity=participant_identity,
                    wait_until_answered=False,
                    # protobuf's generated stub says Duration|Mapping|None, but
                    # Duration is a well-known type whose real __init__ accepts
                    # a plain timedelta (confirmed at runtime) — the stub is
                    # simply wrong here.
                    max_call_duration=_MAX_CALL_DURATION,  # type: ignore[arg-type]
                )
            )
        except lk_api.TwirpError as exc:
            # Distinct from AGENT_DISPATCH_FAILED — this means the SIP
            # trunk/outbound call request itself was rejected (bad trunk id,
            # malformed number, trunk auth failure, etc.), not an agent-side
            # problem (spec: report the exact LiveKit/SIP error, not a guess).
            logger.error(
                "SIP_PARTICIPANT_FAILED",
                screening_id=screening_id,
                room_name=room_name,
                sip_trunk_id=settings.hr_sip_trunk_id,
                provider_error_code=exc.code,
                provider_status=exc.status,
            )
            raise SipParticipantError(
                f"LiveKit rejected the outbound SIP call (code={exc.code}, status={exc.status}): "
                f"{exc.message}"
            ) from exc
        logger.info(
            "SIP_PARTICIPANT_ACCEPTED",
            screening_id=screening_id,
            room_name=room_name,
            sip_call_id=sip_participant.sip_call_id,
            participant_identity=sip_participant.participant_identity,
        )
    finally:
        await client.aclose()

    return DispatchedCall(
        room_name=room_name,
        dispatch_id=dispatch.id,
        sip_participant_identity=sip_participant.participant_identity,
    )


async def end_screening_call(room_name: str) -> None:
    client = _client()
    try:
        await client.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
    finally:
        await client.aclose()
