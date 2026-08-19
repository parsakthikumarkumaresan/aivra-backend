from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.api.dependencies import require_voice_role
from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.call_repository import CallRepository, TranscriptRepository
from app.ai_employees.voice.repositories.telephony_repository import PhoneNumberRepository
from app.ai_employees.voice.repositories.tool_execution_repository import ToolExecutionRepository
from app.ai_employees.voice.repositories.tool_repository import ToolRepository
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.schemas.customer import (
    CustomerCallResponse,
    CustomerToolExecutionSummary,
    CustomerVoiceToolSummary,
    SimulatorRequest,
    SimulatorResultResponse,
    VoiceBasicEscalationPreferences,
    VoiceEmployeeConfigResponse,
    VoiceNotificationPreferences,
)
from app.ai_employees.voice.services.voice_agent_service import VoiceAgentService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import OrgRole
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/voice", tags=["Customer Voice"])


@router.get("/config", response_model=VoiceEmployeeConfigResponse)
async def get_voice_employee_config(
    auth: AuthContext = Depends(
        require_voice_role(
            OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> VoiceEmployeeConfigResponse:
    org_id = auth.require_organization_id()
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)
    tool_repo = ToolRepository(db)
    phone_repo = PhoneNumberRepository(db)

    agents = await agent_repo.list_for_organization(org_id)
    if not agents:
        raise NotFoundError("No Voice employee configured for this organization.")

    agent = agents[0]
    active_version = await version_repo.get_active_published(org_id, agent.id)
    if active_version is None:
        draft = await version_repo.get_draft(org_id, agent.id)
        if draft is None:
            raise NotFoundError("No active or draft voice configuration found.")
        active_version = draft

    # Fetch phone number detail
    phone_number_str = ""
    if agent.assigned_phone_number_id:
        phone = await phone_repo.get_by_id(org_id, agent.assigned_phone_number_id)
        if phone:
            phone_number_str = phone.number

    # Customer-safe tool summaries
    tools_db = await tool_repo.list_by_ids(org_id, active_version.tool_ids)
    customer_tools = [
        CustomerVoiceToolSummary(
            id=t.id,
            name=t.name,
            description=t.description or "",
            permission="allow",
            risk="low",
            approval_required=False,
            connected=t.enabled,
        )
        for t in tools_db
    ]

    prompt_cfg = active_version.prompt_config or {}
    voice_cfg = active_version.voice_config or {}

    return VoiceEmployeeConfigResponse(
        business_name=agent.name,
        industry=agent.industry or "General",
        description=prompt_cfg.get("introMessage", ""),
        timezone="UTC",
        working_hours="9:00 AM - 5:00 PM",
        language=voice_cfg.get("language", "en-US"),
        voice=voice_cfg.get("voiceName", "Nova"),
        tone="professional",
        greeting=prompt_cfg.get("introMessage", "Hello! How can I assist you today?"),
        fallback_message="I'm sorry, could you please repeat that?",
        speaking_style="clear and friendly",
        knowledge_source_ids=active_version.library.get("knowledgeSourceIds", []),
        capabilities=["support", "booking", "faq"],
        tools=customer_tools,
        escalation_rules=[],
        phone_provider="Twilio",
        phone_number=phone_number_str,
        inbound_enabled=True,
        outbound_enabled=True,
        employee_name=agent.name,
        notification_preferences=VoiceNotificationPreferences(),
        basic_escalation_preferences=VoiceBasicEscalationPreferences(),
    )


@router.patch("/config", response_model=VoiceEmployeeConfigResponse)
async def update_voice_employee_config(
    patch: dict[str, Any],
    auth: AuthContext = Depends(
        require_voice_role(OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER)
    ),
    db: AsyncSession = Depends(get_db),
) -> VoiceEmployeeConfigResponse:
    org_id = auth.require_organization_id()
    agent_repo = VoiceAgentRepository(db)
    version_repo = AgentVersionRepository(db)
    service = VoiceAgentService(agent_repo, version_repo)

    agents = await service.list_agents(org_id)
    if not agents:
        raise NotFoundError("No Voice agent found.")
    agent = agents[0]

    # Shallow-merge editable customer fields into current draft
    draft = await service.get_draft(org_id, agent.id)
    if "employeeName" in patch:
        agent.name = str(patch["employeeName"])
    if "greeting" in patch:
        prompt_cfg = dict(draft.prompt_config)
        prompt_cfg["introMessage"] = str(patch["greeting"])
        draft.prompt_config = prompt_cfg

    return await get_voice_employee_config(auth=auth, db=db)


@router.get("/calls", response_model=list[CustomerCallResponse])
async def list_customer_calls(
    intent: str | None = Query(None),
    outcome: str | None = Query(None),
    escalated: bool | None = Query(None),
    auth: AuthContext = Depends(
        require_voice_role(
            OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> list[CustomerCallResponse]:
    org_id = auth.require_organization_id()
    call_repo = CallRepository(db)
    transcript_repo = TranscriptRepository(db)
    exec_repo = ToolExecutionRepository(db)
    tool_repo = ToolRepository(db)

    calls = await call_repo.list_for_organization(
        org_id, intent=intent, outcome=outcome, escalated=escalated
    )
    responses = []

    for call in calls:
        transcript = await transcript_repo.get_by_call_id(org_id, call.id)
        executions = await exec_repo.list_for_call(org_id, call.id)

        customer_tools_used = []
        for ex in executions:
            t = await tool_repo.get_by_id(org_id, ex.tool_id)
            customer_tools_used.append(
                CustomerToolExecutionSummary(
                    id=ex.id,
                    tool_name=t.name if t else "Tool",
                    input=str(ex.input),
                    result=str(ex.output),
                    status=ex.status.value,
                    latency_ms=ex.duration_ms,
                    timestamp=ex.timestamp,
                )
            )

        responses.append(
            CustomerCallResponse(
                id=call.id,
                caller_name=call.caller_name or "Caller",
                caller_number=call.caller_number or "Unknown",
                employee_id=call.voice_agent_id,
                started_at=call.started_at,
                duration_seconds=call.duration_seconds,
                intent=call.intent.value if call.intent else "unknown",
                outcome=call.outcome.value if call.outcome else "resolved",
                escalated=call.escalated,
                escalation_reason=call.escalation_reason,
                recording_available=call.recording_available,
                summary=call.summary or "",
                transcript=transcript.turns if transcript else [],
                tools_used=customer_tools_used,
                actions_taken=[],
            )
        )

    return responses


@router.get("/calls/{call_id}", response_model=CustomerCallResponse)
async def get_customer_call(
    call_id: str,
    auth: AuthContext = Depends(
        require_voice_role(
            OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> CustomerCallResponse:
    org_id = auth.require_organization_id()
    call_repo = CallRepository(db)
    call = await call_repo.get_by_id(org_id, call_id)
    if call is None:
        raise NotFoundError("Call not found.")

    transcript = await TranscriptRepository(db).get_by_call_id(org_id, call.id)
    executions = await ToolExecutionRepository(db).list_for_call(org_id, call.id)
    tool_repo = ToolRepository(db)

    customer_tools_used = []
    for ex in executions:
        t = await tool_repo.get_by_id(org_id, ex.tool_id)
        customer_tools_used.append(
            CustomerToolExecutionSummary(
                id=ex.id,
                tool_name=t.name if t else "Tool",
                input=str(ex.input),
                result=str(ex.output),
                status=ex.status.value,
                latency_ms=ex.duration_ms,
                timestamp=ex.timestamp,
            )
        )

    return CustomerCallResponse(
        id=call.id,
        caller_name=call.caller_name or "Caller",
        caller_number=call.caller_number or "Unknown",
        employee_id=call.voice_agent_id,
        started_at=call.started_at,
        duration_seconds=call.duration_seconds,
        intent=call.intent.value if call.intent else "unknown",
        outcome=call.outcome.value if call.outcome else "resolved",
        escalated=call.escalated,
        escalation_reason=call.escalation_reason,
        recording_available=call.recording_available,
        summary=call.summary or "",
        transcript=transcript.turns if transcript else [],
        tools_used=customer_tools_used,
        actions_taken=[],
    )


@router.post("/simulate", response_model=SimulatorResultResponse)
async def simulate_scenario(
    req: SimulatorRequest,
    auth: AuthContext = Depends(
        require_voice_role(
            OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER
        )
    ),
) -> SimulatorResultResponse:
    user_prompt = req.user_text or f"Testing scenario: {req.scenario}"
    sim_transcript = [
        {"speaker": "customer", "text": user_prompt},
        {"speaker": "agent", "text": f"Simulation response for scenario '{req.scenario}'."},
    ]

    return SimulatorResultResponse(
        outcome="pass",
        transcript=sim_transcript,
        tool_result=f"Simulated execution for {req.scenario}",
        configurationSuggestion=None,
    )
