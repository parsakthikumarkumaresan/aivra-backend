"""Voice real-time runtime abstraction (spec section 11; ADR 0002: LiveKit).

The control plane (FastAPI) never runs the real-time audio loop itself —
it only orchestrates rooms/tokens/dispatch through this interface. The
actual STT -> agent -> LLM -> TTS loop runs in a separate, independently
scalable worker process (app.ai_employees.voice.runtime.agent_worker),
exactly like the HR resume pipeline runs in the RQ worker rather than
inline with a request (spec: "Runtime must scale independently from the
control plane").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeRoom:
    room_name: str
    room_sid: str


@dataclass(frozen=True)
class RuntimeWebhookEvent:
    event_type: str
    room_name: str | None
    participant_identity: str | None
    raw: dict


class VoiceRuntimeProvider(ABC):
    @abstractmethod
    async def create_room(self, *, room_name: str, metadata: str) -> RuntimeRoom: ...

    @abstractmethod
    def generate_access_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        metadata: str,
        ttl_seconds: int,
    ) -> str: ...

    @abstractmethod
    async def dispatch_agent(self, *, room_name: str, agent_name: str, metadata: str) -> str: ...

    @abstractmethod
    async def end_room(self, *, room_name: str) -> None: ...

    @abstractmethod
    def verify_webhook(self, *, body: str, auth_header: str) -> RuntimeWebhookEvent: ...
