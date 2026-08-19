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
from app.audit.models.audit_event import AuditEvent
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


async def _setup_internal_voice_user(
    session: AsyncSession, org_id: str = "org_voice_builder_1"
) -> tuple[User, Organization, str]:
    org = Organization(id=org_id, name="Builder Org", slug=org_id)
    session.add(org)
    await session.flush()
    await _activate_voice(session, org.id)

    user = User(
        email=f"engineer_{org_id}@aivra.ai",
        full_name="Voice Engineer",
        password_hash="hash",
        platform_role=PlatformRole.AIVRA_ENGINEER,
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
        session_id="ses_test_1",
    )
    return user, org, token


@pytest.mark.asyncio
async def test_voice_agent_builder_full_flow(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, org, token = await _setup_internal_voice_user(db_session, "org_vb_flow_1")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Agent
    create_resp = await client.post(
        "/api/v1/internal/voice-agents",
        json={"name": "Sales Representative", "industry": "Technology"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    agent_data = create_resp.json()
    agent_id = agent_data["id"]
    assert agent_data["status"] == "draft"
    assert agent_data["version"] == 1

    # 2. Get Agent
    get_resp = await client.get(f"/api/v1/internal/voice-agents/{agent_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Sales Representative"

    # 3. Update Draft (PATCH shallow merge)
    patch_resp = await client.patch(
        f"/api/v1/internal/voice-agents/{agent_id}",
        json={
            "patch": {
                "promptConfig": {
                    "introMessage": "Welcome to AIVRA Sales!",
                    "systemPrompt": "You are a top sales executive.",
                }
            }
        },
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["promptConfig"]["introMessage"] == "Welcome to AIVRA Sales!"

    # 4. Lifecycle: Submit Test -> Approve -> Publish
    test_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/submit-test", headers=headers
    )
    assert test_resp.status_code == 200
    assert test_resp.json()["status"] == "test"

    approve_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/approve", headers=headers
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    publish_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/publish", headers=headers
    )
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "published"
    published_ver_id = publish_resp.json()["id"]

    # 5. List Versions (Assert new draft v2 was opened after publishing v1)
    versions_resp = await client.get(
        f"/api/v1/internal/voice-agents/{agent_id}/versions", headers=headers
    )
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) == 2  # v1 (published) and v2 (new draft)

    # 6. Pause and Resume
    pause_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/pause", headers=headers
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    resume_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/resume", headers=headers
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "live"

    # 7. Rollback to v1
    rollback_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/rollback",
        json={"targetVersionId": published_ver_id},
        headers=headers,
    )
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["status"] == "published"
    assert rollback_resp.json()["versionNumber"] == 3

    # 8. Test Message
    test_msg_resp = await client.post(
        f"/api/v1/internal/voice-agents/{agent_id}/test-message",
        json={"userText": "Hello, tell me about product pricing"},
        headers=headers,
    )
    assert test_msg_resp.status_code == 200
    assert "agentTurn" in test_msg_resp.json()

    # 9. Verify Audit Events created
    audit_stmt = select(AuditEvent).where(AuditEvent.organization_id == org.id)
    audit_res = await db_session.execute(audit_stmt)
    events = list(audit_res.scalars().all())
    action_types = {e.action for e in events}
    assert "voice_agent.created" in action_types
    assert "voice_agent.published" in action_types
