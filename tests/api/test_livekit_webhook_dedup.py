from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.agent_version import AgentVersion, AgentVersionStatus
from app.ai_employees.voice.models.call import Call, CallDirection, CallStatus
from app.ai_employees.voice.models.voice_agent import VoiceAgent
from app.identity.models.user import User
from app.organizations.models.organization import Organization


async def _setup_webhook_call(
    session: AsyncSession, org_id: str = "org_webhook_1"
) -> tuple[Organization, Call]:
    org = Organization(id=org_id, name="Webhook Org", slug=org_id)
    session.add(org)
    await session.flush()

    user = User(
        email=f"user_{org_id}@example.com",
        full_name="Webhook User",
        password_hash="hash",
    )
    session.add(user)
    await session.flush()

    agent = VoiceAgent(organization_id=org.id, name="Webhook Agent")
    session.add(agent)
    await session.flush()

    version = AgentVersion(
        organization_id=org.id,
        voice_agent_id=agent.id,
        version_number=1,
        status=AgentVersionStatus.PUBLISHED,
        is_active=True,
        created_by_user_id=user.id,
    )
    session.add(version)
    await session.flush()

    call = Call(
        id="call_web_1",
        organization_id=org.id,
        voice_agent_id=agent.id,
        agent_version_id=version.id,
        room_name="room_test_web_1",
        direction=CallDirection.INBOUND,
        status=CallStatus.IN_PROGRESS,
        started_at=datetime.now(UTC),
    )
    session.add(call)
    await session.flush()
    return org, call


@pytest.mark.asyncio
async def test_livekit_webhook_duplicate_event_idempotency(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org, call = await _setup_webhook_call(db_session, "org_web_dedup_1")

    webhook_payload = {
        "id": "evt_unique_12345",
        "event": "room_started",
        "room": {"name": call.room_name},
    }

    # First webhook post
    resp1 = await client.post(
        "/api/v1/internal/voice/webhooks/livekit",
        json=webhook_payload,
        headers={"Authorization": "mock_valid_auth"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "processed"

    # Second webhook post (Duplicate replay with exact same event ID)
    resp2 = await client.post(
        "/api/v1/internal/voice/webhooks/livekit",
        json=webhook_payload,
        headers={"Authorization": "mock_valid_auth"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "already_processed"
    assert resp2.json()["event_id"] == "evt_unique_12345"
