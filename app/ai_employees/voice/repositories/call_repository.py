from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.call import Call
from app.ai_employees.voice.models.call_event import CallEvent
from app.ai_employees.voice.models.recording import Recording
from app.ai_employees.voice.models.transcript import Transcript
from app.shared.database.repository import OrgScopedRepository


class CallRepository(OrgScopedRepository[Call]):
    model = Call

    async def list_for_agent(self, organization_id: str, voice_agent_id: str) -> list[Call]:
        stmt = (
            select(Call)
            .where(
                Call.organization_id == organization_id,
                Call.voice_agent_id == voice_agent_id,
            )
            .order_by(Call.started_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_organization(
        self,
        organization_id: str,
        *,
        intent: str | None = None,
        outcome: str | None = None,
        escalated: bool | None = None,
    ) -> list[Call]:
        stmt = select(Call).where(Call.organization_id == organization_id)
        if intent is not None:
            stmt = stmt.where(Call.intent == intent)
        if outcome is not None:
            stmt = stmt.where(Call.outcome == outcome)
        if escalated is not None:
            stmt = stmt.where(Call.escalated.is_(escalated))
        stmt = stmt.order_by(Call.started_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_provider_call_id(
        self, organization_id: str, provider_call_id: str
    ) -> Call | None:
        stmt = select(Call).where(
            Call.organization_id == organization_id,
            Call.provider_call_id == provider_call_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_room_name(self, room_name: str) -> Call | None:
        stmt = select(Call).where(Call.room_name == room_name)
        result = await self.session.execute(stmt)
        return result.scalars().first()


class CallEventRepository(OrgScopedRepository[CallEvent]):
    model = CallEvent

    async def list_for_call(self, organization_id: str, call_id: str) -> list[CallEvent]:
        stmt = (
            select(CallEvent)
            .where(
                CallEvent.organization_id == organization_id,
                CallEvent.call_id == call_id,
            )
            .order_by(CallEvent.occurred_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_event_type_and_timestamp(
        self, organization_id: str, call_id: str, event_type: str, timestamp: str
    ) -> CallEvent | None:
        stmt = select(CallEvent).where(
            CallEvent.organization_id == organization_id,
            CallEvent.call_id == call_id,
            CallEvent.event_type == event_type,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class TranscriptRepository(OrgScopedRepository[Transcript]):
    model = Transcript

    async def get_by_call_id(self, organization_id: str, call_id: str) -> Transcript | None:
        stmt = select(Transcript).where(
            Transcript.organization_id == organization_id,
            Transcript.call_id == call_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class RecordingRepository(OrgScopedRepository[Recording]):
    model = Recording

    async def get_by_call_id(self, organization_id: str, call_id: str) -> Recording | None:
        stmt = select(Recording).where(
            Recording.organization_id == organization_id,
            Recording.call_id == call_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
