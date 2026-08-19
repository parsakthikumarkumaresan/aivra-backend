from __future__ import annotations

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
from app.identity.models.user import User
from app.organizations.models.membership import OrganizationMember
from app.organizations.models.organization import Organization
from app.shared.rbac.roles import OrgRole, PlatformRole
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


async def _setup_telephony_admin(
    session: AsyncSession, org_id: str = "org_tel_api_1"
) -> tuple[User, Organization, str]:
    org = Organization(id=org_id, name="Telephony Org", slug=org_id)
    session.add(org)
    await session.flush()
    await _activate_voice(session, org.id)

    user = User(
        email=f"admin_{org_id}@aivra.ai",
        full_name="Telephony Admin",
        password_hash="hash",
        platform_role=PlatformRole.AIVRA_ADMIN,
    )
    session.add(user)
    await session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.OWNER,
    )
    session.add(member)
    await session.flush()

    token = create_access_token(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRole.OWNER.value,
        session_id="ses_test_3",
    )
    return user, org, token


@pytest.mark.asyncio
async def test_telephony_routes_full_flow(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, org, token = await _setup_telephony_admin(db_session, "org_tel_flow_1")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Connect Provider
    provider_resp = await client.post(
        "/api/v1/internal/telephony/providers",
        json={"providerType": "twilio", "accountLabel": "Production Twilio"},
        headers=headers,
    )
    assert provider_resp.status_code == 201
    prov_id = provider_resp.json()["id"]

    # 2. Add Phone Number
    number_resp = await client.post(
        "/api/v1/internal/telephony/numbers",
        json={"number": "+15550188", "country": "US", "providerAccountId": prov_id},
        headers=headers,
    )
    assert number_resp.status_code == 201

    # 3. List Numbers
    list_num_resp = await client.get("/api/v1/internal/telephony/numbers", headers=headers)
    assert list_num_resp.status_code == 200
    assert len(list_num_resp.json()) == 1

    # 4. Create SIP Trunk
    trunk_resp = await client.post(
        "/api/v1/internal/telephony/trunks",
        json={"name": "BYOC Trunk", "providerAccountId": prov_id, "host": "sip.provider.com"},
        headers=headers,
    )
    assert trunk_resp.status_code == 201
    assert trunk_resp.json()["host"] == "sip.provider.com"

    # 5. DND Entry
    dnd_resp = await client.post(
        "/api/v1/internal/telephony/dnd",
        json={"number": "+15559988", "reason": "Opt-out"},
        headers=headers,
    )
    assert dnd_resp.status_code == 201

    # 6. Routing Rule
    route_resp = await client.post(
        "/api/v1/internal/telephony/routes",
        json={"name": "After Hours", "condition": "after_hours", "destination": "voicemail"},
        headers=headers,
    )
    assert route_resp.status_code == 201
    assert route_resp.json()["destination"] == "voicemail"
