from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.models.provision import EmployeeProvision, ProvisionStatus
from app.ai_employees.registry.models.catalog import (
    AIEmployeeType,
    CommercialModel,
    EmployeeTypeCode,
)
from app.ai_employees.voice.models.agent_version import AgentVersion, AgentVersionStatus
from app.ai_employees.voice.models.call import Call, CallDirection, CallStatus
from app.ai_employees.voice.models.transcript import Transcript
from app.ai_employees.voice.models.voice_agent import VoiceAgent, VoiceAgentStatus
from app.identity.models.user import User
from app.organizations.models.membership import OrganizationMember
from app.organizations.models.organization import Organization
from app.shared.rbac.roles import OrgRole
from app.shared.security.tokens import create_access_token


async def _activate_voice(session: AsyncSession, organization_id: str) -> None:
    res = await session.execute(
        select(AIEmployeeType).where(AIEmployeeType.code == EmployeeTypeCode.VOICE)
    )
    voice_type = res.scalars().first()
    if voice_type is None:
        voice_type = AIEmployeeType(
            code=EmployeeTypeCode.VOICE,
            name="AI Voice Employee",
            description="Voice automation",
            commercial_model=CommercialModel.MANAGED_CUSTOM,
        )
        session.add(voice_type)
        await session.flush()
    session.add(
        EmployeeProvision(
            organization_id=organization_id,
            employee_type_id=voice_type.id,
            status=ProvisionStatus.ACTIVE,
        )
    )
    await session.flush()


async def _setup_customer_voice_user(
    session: AsyncSession, org_id: str = "org_customer_voice_1"
) -> tuple[User, Organization, str, VoiceAgent]:
    org = Organization(id=org_id, name="Customer Tenant", slug=org_id)
    session.add(org)
    await session.flush()
    await _activate_voice(session, org.id)

    user = User(
        email=f"customer_{org_id}@example.com",
        full_name="Customer Admin",
        password_hash="hash",
    )
    session.add(user)
    await session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.CUSTOMER_VOICE_USER,
    )
    session.add(member)
    await session.flush()

    agent = VoiceAgent(organization_id=org.id, name="Acme Support", status=VoiceAgentStatus.LIVE)
    session.add(agent)
    await session.flush()

    version = AgentVersion(
        organization_id=org.id,
        voice_agent_id=agent.id,
        version_number=1,
        status=AgentVersionStatus.PUBLISHED,
        is_active=True,
        created_by_user_id=user.id,
        prompt_config={"introMessage": "Welcome to Acme Support!"},
        voice_config={"voiceName": "Nova", "language": "en-US"},
    )
    session.add(version)
    await session.flush()

    call = Call(
        id="call_cust_1",
        organization_id=org.id,
        voice_agent_id=agent.id,
        agent_version_id=version.id,
        direction=CallDirection.INBOUND,
        status=CallStatus.COMPLETED,
        started_at=datetime.now(UTC),
        duration_seconds=90,
        summary="Customer asked for hours.",
    )
    session.add(call)

    transcript = Transcript(
        organization_id=org.id,
        call_id=call.id,
        turns=[{"speaker": "customer", "text": "What are your business hours?"}],
    )
    session.add(transcript)
    await session.flush()

    token = create_access_token(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRole.CUSTOMER_VOICE_USER.value,
        session_id="ses_test_2",
    )
    return user, org, token, agent


@pytest.mark.asyncio
async def test_customer_voice_flow(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, org, token, agent = await _setup_customer_voice_user(db_session, "org_vc_flow_1")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET Customer Voice Config
    config_resp = await client.get("/api/v1/voice/config", headers=headers)
    assert config_resp.status_code == 200
    cfg = config_resp.json()
    assert cfg["businessName"] == "Acme Support"
    assert cfg["greeting"] == "Welcome to Acme Support!"

    # 2. GET Customer Calls List
    calls_resp = await client.get("/api/v1/voice/calls", headers=headers)
    assert calls_resp.status_code == 200
    calls = calls_resp.json()
    assert len(calls) == 1
    assert calls[0]["id"] == "call_cust_1"
    assert calls[0]["summary"] == "Customer asked for hours."

    # 3. GET Call Detail
    detail_resp = await client.get("/api/v1/voice/calls/call_cust_1", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["transcript"][0]["text"] == "What are your business hours?"

    # 4. POST Simulator
    sim_resp = await client.post(
        "/api/v1/voice/simulate",
        json={"scenario": "faq", "userText": "Can I cancel my order?"},
        headers=headers,
    )
    assert sim_resp.status_code == 200
    assert sim_resp.json()["outcome"] == "pass"

    # 5. GET Analytics
    analytics_resp = await client.get("/api/v1/analytics/voice", headers=headers)
    assert analytics_resp.status_code == 200
    assert analytics_resp.json()["totalCalls"] == 1
