from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.agent_version import AgentVersion, AgentVersionStatus
from app.ai_employees.voice.models.call import Call, CallDirection, CallStatus
from app.ai_employees.voice.models.tool import ToolAuthType, ToolKind, ToolMethod
from app.ai_employees.voice.models.tool_execution import ToolExecutionStatus
from app.ai_employees.voice.models.voice_agent import VoiceAgent
from app.ai_employees.voice.repositories.tool_execution_repository import ToolExecutionRepository
from app.ai_employees.voice.repositories.tool_repository import ToolRepository
from app.ai_employees.voice.services.tool_execution_service import ToolExecutionService
from app.ai_employees.voice.services.tool_service import ToolService
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.shared.errors.exceptions import ValidationAppError


async def _create_test_org(session: AsyncSession, org_id: str) -> Organization:
    org = Organization(id=org_id, name=f"Org {org_id}", slug=org_id)
    session.add(org)
    await session.flush()
    return org


async def _create_test_call(session: AsyncSession, org_id: str, call_id: str) -> Call:
    user = User(
        email=f"user_{org_id}@example.com",
        full_name="Test User",
        password_hash="hash",
    )
    session.add(user)
    await session.flush()

    agent = VoiceAgent(organization_id=org_id, name="Test Agent")
    session.add(agent)
    await session.flush()

    version = AgentVersion(
        organization_id=org_id,
        voice_agent_id=agent.id,
        version_number=1,
        status=AgentVersionStatus.PUBLISHED,
        is_active=True,
        created_by_user_id=user.id,
    )
    session.add(version)
    await session.flush()

    call = Call(
        id=call_id,
        organization_id=org_id,
        voice_agent_id=agent.id,
        agent_version_id=version.id,
        direction=CallDirection.INBOUND,
        status=CallStatus.IN_PROGRESS,
        started_at=datetime.now(UTC),
    )
    session.add(call)
    await session.flush()
    return call


@pytest.mark.asyncio
async def test_tool_crud_and_validation(db_session: AsyncSession) -> None:
    org_id = "org_test_tool_1"
    await _create_test_org(db_session, org_id)

    tool_repo = ToolRepository(db_session)
    tool_service = ToolService(tool_repo)

    with pytest.raises(ValidationAppError):
        await tool_service.create_tool(
            organization_id=org_id,
            name="Invalid API Tool",
            kind=ToolKind.API,
            endpoint="ftp://invalid.com",
        )

    tool = await tool_service.create_tool(
        organization_id=org_id,
        name="Booking Tool",
        description="Books an appointment",
        kind=ToolKind.API,
        endpoint="https://api.example.com/appointments",
        method=ToolMethod.POST,
        auth_type=ToolAuthType.BEARER,
        credential_ref="secret_token_123",
        input_schema={"type": "object", "properties": {"date": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"bookingId": {"type": "string"}}},
    )

    assert tool.id.startswith("tool_")
    assert tool.enabled is True
    assert tool.version == 1

    updated = await tool_service.update_tool(
        org_id, tool.id, name="Updated Booking Tool", enabled=False
    )
    assert updated.name == "Updated Booking Tool"
    assert updated.enabled is False
    assert updated.version == 2

    tools = await tool_service.list_tools(org_id)
    assert len(tools) == 1
    assert tools[0].id == tool.id


@pytest.mark.asyncio
async def test_tool_execution_internal_and_disabled(db_session: AsyncSession) -> None:
    org_id = "org_test_tool_2"
    call_id = "call_test_1"
    await _create_test_org(db_session, org_id)
    await _create_test_call(db_session, org_id, call_id)

    tool_repo = ToolRepository(db_session)
    exec_repo = ToolExecutionRepository(db_session)

    tool_service = ToolService(tool_repo)
    exec_service = ToolExecutionService(tool_repo, exec_repo)

    tool = await tool_service.create_tool(
        organization_id=org_id,
        name="Transfer Call",
        kind=ToolKind.TRANSFER,
        endpoint="internal://telephony/transfer",
    )

    result = await exec_service.execute_tool(
        org_id, call_id, tool.id, {"destination": "+15550199"}
    )

    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.output["action"] == "internal://telephony/transfer"
    assert result.error_code is None

    # Disable tool and verify execution fails cleanly
    await tool_service.toggle_tool(org_id, tool.id, enabled=False)
    result_disabled = await exec_service.execute_tool(
        org_id, call_id, tool.id, {"destination": "+15550199"}
    )
    assert result_disabled.status == ToolExecutionStatus.FAILED
    assert result_disabled.error_code == "TOOL_DISABLED"


@pytest.mark.asyncio
async def test_tool_execution_api_mock(db_session: AsyncSession) -> None:
    org_id = "org_test_tool_3"
    call_id = "call_test_2"
    await _create_test_org(db_session, org_id)
    await _create_test_call(db_session, org_id, call_id)

    tool_repo = ToolRepository(db_session)
    exec_repo = ToolExecutionRepository(db_session)

    tool_service = ToolService(tool_repo)

    tool = await tool_service.create_tool(
        organization_id=org_id,
        name="Status Check API",
        kind=ToolKind.API,
        endpoint="https://api.example.com/status",
        method=ToolMethod.POST,
        auth_type=ToolAuthType.BEARER,
        credential_ref="test_key",
    )

    # Use respx/httpx mock transport
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test_key"
        return httpx.Response(200, json={"status": "confirmed", "code": 100})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        exec_service = ToolExecutionService(tool_repo, exec_repo, http_client=client)
        result = await exec_service.execute_tool(
            org_id, call_id, tool.id, {"orderId": "ORD-99"}
        )

    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.output == {"status": "confirmed", "code": 100}
