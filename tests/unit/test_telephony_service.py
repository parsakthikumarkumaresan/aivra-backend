from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.phone_number import PhoneNumberStatus
from app.ai_employees.voice.models.routing_rule import RoutingCondition
from app.ai_employees.voice.models.telephony_provider import (
    TelephonyAccountStatus,
    TelephonyProviderType,
)
from app.ai_employees.voice.models.voice_agent import VoiceAgent
from app.ai_employees.voice.repositories.telephony_repository import (
    ComplianceRecordRepository,
    DndEntryRepository,
    PhoneNumberRepository,
    RoutingRuleRepository,
    SipTrunkRepository,
    TelephonyProviderAccountRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.services.telephony_service import TelephonyService
from app.organizations.models.organization import Organization


async def _create_test_org(session: AsyncSession, org_id: str) -> Organization:
    org = Organization(id=org_id, name=f"Org {org_id}", slug=org_id)
    session.add(org)
    await session.flush()
    return org


@pytest.mark.asyncio
async def test_telephony_service_flow(db_session: AsyncSession) -> None:
    org_id = "org_test_telephony_1"
    await _create_test_org(db_session, org_id)

    phone_repo = PhoneNumberRepository(db_session)
    account_repo = TelephonyProviderAccountRepository(db_session)
    sip_repo = SipTrunkRepository(db_session)
    compliance_repo = ComplianceRecordRepository(db_session)
    dnd_repo = DndEntryRepository(db_session)
    routing_repo = RoutingRuleRepository(db_session)
    agent_repo = VoiceAgentRepository(db_session)

    service = TelephonyService(
        phone_repo,
        account_repo,
        sip_repo,
        compliance_repo,
        dnd_repo,
        routing_repo,
        agent_repo,
    )

    # 1. Connect Account
    account = await service.connect_provider_account(
        org_id, TelephonyProviderType.TWILIO, account_label="Main Twilio"
    )
    assert account.status == TelephonyAccountStatus.CONNECTED

    # 2. Add Phone Number
    phone = await service.add_phone_number(
        org_id, number="+15550199", country="US", provider_account_id=account.id
    )
    assert phone.status == PhoneNumberStatus.UNASSIGNED

    # 3. Create Agent and Assign Number
    agent = VoiceAgent(organization_id=org_id, name="Frontdesk Agent")
    agent_repo.session.add(agent)
    await agent_repo.session.flush()

    assigned_phone = await service.assign_phone_number_to_agent(org_id, phone.id, agent.id)
    assert assigned_phone.status == PhoneNumberStatus.ACTIVE
    assert agent.assigned_phone_number_id == phone.id

    # 4. Unassign Number
    unassigned = await service.unassign_phone_number(org_id, phone.id)
    assert unassigned.status == PhoneNumberStatus.UNASSIGNED
    assert agent.assigned_phone_number_id is None

    # 5. DND Entry
    await service.add_dnd_entry(org_id, "+15559999", reason="User opt-out")
    assert await service.is_dnd(org_id, "+15559999") is True
    assert await service.is_dnd(org_id, "+15550000") is False

    # 6. Routing Rule
    rule = await service.create_routing_rule(
        org_id,
        name="After Hours",
        condition=RoutingCondition.AFTER_HOURS,
        destination="voicemail",
    )
    assert rule.destination == "voicemail"
