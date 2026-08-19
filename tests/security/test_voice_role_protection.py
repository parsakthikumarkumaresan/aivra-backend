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


async def _create_customer_user_token(
    session: AsyncSession, org_id: str = "org_customer_security_1"
) -> tuple[User, Organization, str]:
    org = Organization(id=org_id, name="Customer Org", slug=org_id)
    session.add(org)
    await session.flush()
    await _activate_voice(session, org.id)

    user = User(
        email=f"customer_{org_id}@example.com",
        full_name="Customer User",
        password_hash="hash",
        platform_role=None,  # Ordinary customer, NO platform role
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

    token = create_access_token(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRole.CUSTOMER_VOICE_USER.value,
        session_id="ses_test_5",
    )
    return user, org, token


@pytest.mark.asyncio
async def test_customer_cannot_reach_internal_voice_builder_routes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, _, token = await _create_customer_user_token(db_session, "org_cust_sec_1")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Customer token trying to list internal voice agents -> 403 Forbidden
    builder_resp = await client.get("/api/v1/internal/voice-agents", headers=headers)
    assert builder_resp.status_code == 403
    assert builder_resp.json()["error"]["code"] == "FORBIDDEN"

    # 2. Customer token trying to list internal telephony numbers -> 403 Forbidden
    telephony_resp = await client.get("/api/v1/internal/telephony/numbers", headers=headers)
    assert telephony_resp.status_code == 403
    assert telephony_resp.json()["error"]["code"] == "FORBIDDEN"
