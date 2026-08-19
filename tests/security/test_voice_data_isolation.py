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


async def _create_org_user_token(
    session: AsyncSession, org_id: str, platform_role: PlatformRole | None = None
) -> tuple[User, Organization, str]:
    org = Organization(id=org_id, name=f"Org {org_id}", slug=org_id)
    session.add(org)
    await session.flush()
    await _activate_voice(session, org.id)

    user = User(
        email=f"user_{org_id}@example.com",
        full_name=f"User {org_id}",
        password_hash="hash",
        platform_role=platform_role,
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
        session_id="ses_test_4",
    )
    return user, org, token


@pytest.mark.asyncio
async def test_voice_cross_tenant_isolation(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Setup Tenant A with Voice Engineer access
    _, org_a, token_a = await _create_org_user_token(
        db_session, "org_voice_iso_a", PlatformRole.AIVRA_ENGINEER
    )

    # Setup Tenant B with Voice Engineer access
    _, org_b, token_b = await _create_org_user_token(
        db_session, "org_voice_iso_b", PlatformRole.AIVRA_ENGINEER
    )

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant A creates Voice Agent
    create_resp = await client.post(
        "/api/v1/internal/voice-agents",
        json={"name": "Org A Agent", "industry": "Retail"},
        headers=headers_a,
    )
    assert create_resp.status_code == 201
    agent_id_a = create_resp.json()["id"]

    # Tenant B attempts to read Tenant A's agent -> Must be 404 NotFound
    get_resp_b = await client.get(
        f"/api/v1/internal/voice-agents/{agent_id_a}", headers=headers_b
    )
    assert get_resp_b.status_code == 404

    # Tenant B attempts to patch Tenant A's agent draft -> Must be 404 NotFound
    patch_resp_b = await client.patch(
        f"/api/v1/internal/voice-agents/{agent_id_a}",
        json={"patch": {"promptConfig": {"introMessage": "Hacked"}}},
        headers=headers_b,
    )
    assert patch_resp_b.status_code == 404
