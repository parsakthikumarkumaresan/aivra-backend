from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.api.dependencies import require_voice_internal_role
from app.ai_employees.voice.models.agent_version import AgentVersion
from app.ai_employees.voice.models.voice_agent import VoiceAgent
from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.call_repository import (
    CallEventRepository,
    CallRepository,
    TranscriptRepository,
)
from app.ai_employees.voice.repositories.tool_execution_repository import ToolExecutionRepository
from app.ai_employees.voice.repositories.tool_repository import ToolRepository
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.runtime.llm_provider import get_voice_llm_provider
from app.ai_employees.voice.schemas.builder import (
    AgentVersionResponse,
    CreateVoiceAgentRequest,
    ReplayConversationResponse,
    ReplayTimelineEntry,
    ReplayToolCall,
    RollbackVoiceAgentRequest,
    TestMessageRequest,
    TestTurnResultResponse,
    UpdateVoiceAgentDraftRequest,
    VoiceAgentResponse,
)
from app.ai_employees.voice.services.voice_agent_service import VoiceAgentService
from app.audit.models.audit_event import ActorType
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/internal/voice-agents", tags=["Internal Voice Builder"])


def _format_version_response(version: AgentVersion) -> AgentVersionResponse:
    return AgentVersionResponse(
        id=version.id,
        voice_agent_id=version.voice_agent_id,
        version_number=version.version_number,
        status=version.status.value,
        is_active=version.is_active,
        prompt_config=version.prompt_config,
        flow_config=version.flow_config,
        context_config=version.context_config,
        library=version.library,
        tool_ids=version.tool_ids,
        voice_config=version.voice_config,
        transcription_config=version.transcription_config,
        call_end_config=version.call_end_config,
        transfer_config=version.transfer_config,
        analysis_config=version.analysis_config,
        call_actions_config=version.call_actions_config,
        advanced_config=version.advanced_config,
        published_at=version.published_at,
    )


async def _format_agent_response(
    agent: VoiceAgent, version: AgentVersion, tool_repo: ToolRepository
) -> VoiceAgentResponse:
    tools_db = await tool_repo.list_by_ids(agent.organization_id, version.tool_ids)
    tool_dicts = [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description or "",
            "kind": t.kind.value,
            "method": t.method.value,
            "endpoint": t.endpoint,
            "authType": t.auth_type.value,
            "inputs": [
                {"name": k, **v}
                for k, v in t.input_schema.get("properties", {}).items()
            ] if isinstance(t.input_schema.get("properties"), dict) else [],
            "outputs": [
                {"name": k, **v}
                for k, v in t.output_schema.get("properties", {}).items()
            ] if isinstance(t.output_schema.get("properties"), dict) else [],
            "enabled": t.enabled,
        }
        for t in tools_db
    ]

    return VoiceAgentResponse(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        industry=agent.industry,
        status=agent.status.value,
        environment=agent.environment.value,
        version=version.version_number,
        last_updated_at=agent.updated_at,
        assigned_phone_number_id=agent.assigned_phone_number_id,
        prompt_config=version.prompt_config,
        flow_config=version.flow_config,
        context_config=version.context_config,
        library=version.library,
        tools=tool_dicts,
        voice_config=version.voice_config,
        transcription_config=version.transcription_config,
        call_end_config=version.call_end_config,
        transfer_config=version.transfer_config,
        analysis_config=version.analysis_config,
        call_actions_config=version.call_actions_config,
        advanced_config=version.advanced_config,
    )


@router.get("", response_model=list[VoiceAgentResponse])
async def list_voice_agents(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[VoiceAgentResponse]:
    org_id = auth.require_organization_id()
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)
    tool_repo = ToolRepository(db)

    service = VoiceAgentService(agent_repo, version_repo)
    agents = await service.list_agents(org_id)

    responses = []
    for agent in agents:
        draft_or_active = await version_repo.get_draft(org_id, agent.id)
        if draft_or_active is None:
            draft_or_active = await version_repo.get_active_published(org_id, agent.id)
        if draft_or_active is None:
            versions = await version_repo.list_for_agent(org_id, agent.id)
            draft_or_active = versions[0] if versions else None

        if draft_or_active:
            responses.append(await _format_agent_response(agent, draft_or_active, tool_repo))

    return responses


@router.post("", response_model=VoiceAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_voice_agent(
    req: CreateVoiceAgentRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> VoiceAgentResponse:
    org_id = auth.require_organization_id()
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)
    tool_repo = ToolRepository(db)

    service = VoiceAgentService(agent_repo, version_repo)
    agent, draft = await service.create_agent(
        organization_id=org_id,
        created_by_user_id=auth.user.id,
        name=req.name,
        industry=req.industry,
    )

    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_agent.created",
        resource_type="voice_agent",
        resource_id=agent.id,
    )

    return await _format_agent_response(agent, draft, tool_repo)


@router.get("/{agent_id}", response_model=VoiceAgentResponse)
async def get_voice_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> VoiceAgentResponse:
    org_id = auth.require_organization_id()
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)
    tool_repo = ToolRepository(db)

    service = VoiceAgentService(agent_repo, version_repo)
    agent = await service.get_agent(org_id, agent_id)
    draft = await service.get_draft(org_id, agent_id)

    return await _format_agent_response(agent, draft, tool_repo)


@router.patch("/{agent_id}", response_model=VoiceAgentResponse)
async def update_voice_agent_draft(
    agent_id: str,
    req: UpdateVoiceAgentDraftRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> VoiceAgentResponse:
    org_id = auth.require_organization_id()
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)
    tool_repo = ToolRepository(db)

    service = VoiceAgentService(agent_repo, version_repo)
    agent = await service.get_agent(org_id, agent_id)
    draft = await service.update_draft(org_id, agent_id, patch=req.patch)

    return await _format_agent_response(agent, draft, tool_repo)


@router.post("/{agent_id}/submit-test", response_model=AgentVersionResponse)
async def submit_for_test(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> AgentVersionResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    version = await service.submit_for_test(org_id, agent_id)
    return _format_version_response(version)


@router.post("/{agent_id}/approve", response_model=AgentVersionResponse)
async def approve_voice_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> AgentVersionResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    version = await service.approve(org_id, agent_id)

    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_agent.approved",
        resource_type="voice_agent",
        resource_id=agent_id,
    )
    return _format_version_response(version)


@router.post("/{agent_id}/publish", response_model=AgentVersionResponse)
async def publish_voice_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> AgentVersionResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    version = await service.publish(org_id, agent_id)

    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_agent.published",
        resource_type="voice_agent",
        resource_id=agent_id,
    )
    return _format_version_response(version)


@router.post("/{agent_id}/rollback", response_model=AgentVersionResponse)
async def rollback_voice_agent(
    agent_id: str,
    req: RollbackVoiceAgentRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> AgentVersionResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    version = await service.rollback(org_id, agent_id, target_version_id=req.target_version_id)

    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_agent.rolled_back",
        resource_type="voice_agent",
        resource_id=agent_id,
    )
    return _format_version_response(version)


@router.post("/{agent_id}/pause", response_model=VoiceAgentResponse)
async def pause_voice_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> VoiceAgentResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    agent = await service.pause(org_id, agent_id)
    draft = await service.get_draft(org_id, agent_id)

    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_agent.paused",
        resource_type="voice_agent",
        resource_id=agent_id,
    )
    return await _format_agent_response(agent, draft, ToolRepository(db))


@router.post("/{agent_id}/resume", response_model=VoiceAgentResponse)
async def resume_voice_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> VoiceAgentResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    agent = await service.resume(org_id, agent_id)
    draft = await service.get_draft(org_id, agent_id)

    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_agent.resumed",
        resource_type="voice_agent",
        resource_id=agent_id,
    )
    return await _format_agent_response(agent, draft, ToolRepository(db))


@router.get("/{agent_id}/versions", response_model=list[AgentVersionResponse])
async def list_agent_versions(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[AgentVersionResponse]:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    versions = await service.list_versions(org_id, agent_id)
    return [_format_version_response(v) for v in versions]


@router.post("/{agent_id}/test-message", response_model=TestTurnResultResponse)
async def send_test_message(
    agent_id: str,
    req: TestMessageRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> TestTurnResultResponse:
    org_id = auth.require_organization_id()
    service = VoiceAgentService(VoiceAgentRepository(db), AgentVersionRepository(db))
    draft = await service.get_draft(org_id, agent_id)

    system_prompt = draft.prompt_config.get("systemPrompt", "You are an AI assistant.")
    user_turn = {
        "id": "turn_u1",
        "speaker": "customer",
        "text": req.user_text,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Synchronous LLM test turn
    llm = get_voice_llm_provider()
    reply_raw = await llm.extract_structured(
        system_prompt=system_prompt,
        user_content=req.user_text,
        json_schema={
            "type": "object",
            "properties": {"agentResponse": {"type": "string"}},
            "required": ["agentResponse"],
            "additionalProperties": False,
        },
        schema_name="test_message",
    )

    agent_turn = {
        "id": "turn_a1",
        "speaker": "agent",
        "text": reply_raw.get("agentResponse", "Thank you for reaching out."),
        "timestamp": datetime.now(UTC).isoformat(),
    }

    debug = {
        "currentNodeName": draft.flow_config.get("startNodeId", "greeting"),
        "toolCalled": None,
        "knowledgeRetrieved": None,
        "contextSnapshot": {"userPrompt": req.user_text},
    }

    return TestTurnResultResponse(user_turn=user_turn, agent_turn=agent_turn, debug=debug)


@router.get("/{agent_id}/replay-conversations", response_model=list[ReplayConversationResponse])
async def list_replay_conversations(
    agent_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[ReplayConversationResponse]:
    org_id = auth.require_organization_id()
    call_repo = CallRepository(db)
    transcript_repo = TranscriptRepository(db)
    exec_repo = ToolExecutionRepository(db)
    event_repo = CallEventRepository(db)

    calls = await call_repo.list_for_agent(org_id, agent_id)
    replays = []

    for call in calls:
        transcript = await transcript_repo.get_by_call_id(org_id, call.id)
        executions = await exec_repo.list_for_call(org_id, call.id)
        events = await event_repo.list_for_call(org_id, call.id)

        tool_calls = [
            ReplayToolCall(
                id=e.id,
                name=f"Tool_{e.tool_id[:8]}",
                input=str(e.input),
                output=str(e.output),
                status=e.status.value,
                timestamp=e.timestamp.isoformat(),
            )
            for e in executions
        ]

        timeline = [
            ReplayTimelineEntry(
                id=evt.id, label=evt.event_type, timestamp=evt.occurred_at.isoformat()
            )
            for evt in events
        ]

        replays.append(
            ReplayConversationResponse(
                id=call.id,
                agent_id=agent_id,
                customer_name=call.caller_name or call.caller_number or "Caller",
                duration_seconds=call.duration_seconds,
                outcome=call.outcome.value if call.outcome else "resolved",
                started_at=call.started_at,
                transcript=transcript.turns if transcript else [],
                tool_calls=tool_calls,
                knowledge_retrieved=[],
                timeline=timeline,
            )
        )

    return replays


@router.get(
    "/{agent_id}/replay-conversations/{call_id}", response_model=ReplayConversationResponse
)
async def get_replay_conversation(
    agent_id: str,
    call_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> ReplayConversationResponse:
    org_id = auth.require_organization_id()
    call_repo = CallRepository(db)
    call = await call_repo.get_by_id(org_id, call_id)
    if call is None or call.voice_agent_id != agent_id:
        raise NotFoundError("Replay conversation not found.")

    transcript = await TranscriptRepository(db).get_by_call_id(org_id, call.id)
    executions = await ToolExecutionRepository(db).list_for_call(org_id, call.id)
    events = await CallEventRepository(db).list_for_call(org_id, call.id)

    tool_calls = [
        ReplayToolCall(
            id=e.id,
            name=f"Tool_{e.tool_id[:8]}",
            input=str(e.input),
            output=str(e.output),
            status=e.status.value,
            timestamp=e.timestamp.isoformat(),
        )
        for e in executions
    ]

    timeline = [
        ReplayTimelineEntry(id=evt.id, label=evt.event_type, timestamp=evt.occurred_at.isoformat())
        for evt in events
    ]

    return ReplayConversationResponse(
        id=call.id,
        agent_id=agent_id,
        customer_name=call.caller_name or call.caller_number or "Caller",
        duration_seconds=call.duration_seconds,
        outcome=call.outcome.value if call.outcome else "resolved",
        started_at=call.started_at,
        transcript=transcript.turns if transcript else [],
        tool_calls=tool_calls,
        knowledge_retrieved=[],
        timeline=timeline,
    )
