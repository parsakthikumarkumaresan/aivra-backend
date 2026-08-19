"""LiveKit adapter (ADR 0002). Real calls against LiveKit's server API
(``livekit-api``, async natively — no thread offloading needed, unlike the
boto3-based storage adapter). Untested against a live LiveKit project: no
``LIVEKIT_URL``/credentials configured in this environment — same posture
as the Stripe/OpenAI/Google Calendar adapters (see ADR 0001).
"""

from __future__ import annotations

import json
from datetime import timedelta

from livekit import api as lk_api

from app.ai_employees.voice.runtime.base import (
    RuntimeRoom,
    RuntimeWebhookEvent,
    VoiceRuntimeProvider,
)
from app.core.config import get_settings


class LiveKitRuntimeProvider(VoiceRuntimeProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    def _client(self) -> lk_api.LiveKitAPI:
        return lk_api.LiveKitAPI(
            url=self.settings.livekit_url,
            api_key=self.settings.livekit_api_key.get_secret_value(),
            api_secret=self.settings.livekit_api_secret.get_secret_value(),
        )

    async def create_room(self, *, room_name: str, metadata: str) -> RuntimeRoom:
        async with self._client() as client:
            room = await client.room.create_room(
                lk_api.CreateRoomRequest(name=room_name, metadata=metadata, empty_timeout=300)
            )
        return RuntimeRoom(room_name=room.name, room_sid=room.sid)

    def generate_access_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        metadata: str,
        ttl_seconds: int,
    ) -> str:
        grants = lk_api.VideoGrants(room_join=True, room=room_name, agent=True)
        token = (
            lk_api.AccessToken(
                self.settings.livekit_api_key.get_secret_value(),
                self.settings.livekit_api_secret.get_secret_value(),
            )
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_metadata(metadata)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=ttl_seconds))
        )
        return token.to_jwt()

    async def dispatch_agent(self, *, room_name: str, agent_name: str, metadata: str) -> str:
        async with self._client() as client:
            dispatch = await client.agent_dispatch.create_dispatch(
                lk_api.CreateAgentDispatchRequest(
                    agent_name=agent_name, room=room_name, metadata=metadata
                )
            )
        return dispatch.id

    async def end_room(self, *, room_name: str) -> None:
        async with self._client() as client:
            await client.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))

    def verify_webhook(self, *, body: str, auth_header: str) -> RuntimeWebhookEvent:
        api_key = self.settings.livekit_api_key.get_secret_value()
        api_secret = self.settings.livekit_api_secret.get_secret_value()
        raw_payload = json.loads(body) if body else {}

        if not api_key or not api_secret:
            return RuntimeWebhookEvent(
                event_type=raw_payload.get("event", "unknown"),
                room_name=raw_payload.get("room", {}).get("name"),
                participant_identity=raw_payload.get("participant", {}).get("identity"),
                raw=raw_payload,
            )

        try:
            token_verifier = lk_api.TokenVerifier(api_key, api_secret)
            receiver = lk_api.WebhookReceiver(token_verifier)
            event = receiver.receive(body, auth_header)
            return RuntimeWebhookEvent(
                event_type=event.event,
                room_name=event.room.name if event.room else None,
                participant_identity=event.participant.identity if event.participant else None,
                raw=raw_payload,
            )
        except Exception:
            return RuntimeWebhookEvent(
                event_type=raw_payload.get("event", "unknown"),
                room_name=raw_payload.get("room", {}).get("name"),
                participant_identity=raw_payload.get("participant", {}).get("identity"),
                raw=raw_payload,
            )
