from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.agent_version import AgentVersion, AgentVersionStatus
from app.ai_employees.voice.models.call import Call, CallDirection, CallStatus
from app.ai_employees.voice.models.transcript import Transcript
from app.ai_employees.voice.models.voice_agent import VoiceAgent
from app.ai_employees.voice.repositories.call_analysis_repository import CallAnalysisRepository
from app.ai_employees.voice.repositories.call_usage_repository import CallUsageRepository
from app.ai_employees.voice.workflows.call_analysis_pipeline import run_call_analysis_pipeline
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from tests.fakes.fake_ai_providers import FakeLLMProvider


async def _setup_test_call_data(session: AsyncSession, org_id: str, call_id: str) -> Call:
    org = Organization(id=org_id, name=f"Org {org_id}", slug=org_id)
    session.add(org)
    await session.flush()

    user = User(
        email=f"user_{org_id}@example.com",
        full_name="Voice Test User",
        password_hash="hash",
    )
    session.add(user)
    await session.flush()

    agent = VoiceAgent(organization_id=org_id, name="Support Agent")
    session.add(agent)
    await session.flush()

    version = AgentVersion(
        organization_id=org_id,
        voice_agent_id=agent.id,
        version_number=1,
        status=AgentVersionStatus.PUBLISHED,
        is_active=True,
        created_by_user_id=user.id,
        call_end_config={"webhookUrl": "https://api.example.com/webhooks/call-end"},
        analysis_config={"customFields": [{"name": "customerRating", "type": "number"}]},
    )
    session.add(version)
    await session.flush()

    call = Call(
        id=call_id,
        organization_id=org_id,
        voice_agent_id=agent.id,
        agent_version_id=version.id,
        direction=CallDirection.INBOUND,
        status=CallStatus.COMPLETED,
        started_at=datetime.now(UTC),
        duration_seconds=120,
    )
    session.add(call)

    transcript = Transcript(
        organization_id=org_id,
        call_id=call_id,
        turns=[
            {"speaker": "customer", "text": "Hi, I need help resetting my password."},
            {"speaker": "agent", "text": "I can help with that. Sending a reset link now."},
            {"speaker": "customer", "text": "Thank you, I got it!"},
        ],
    )
    session.add(transcript)
    await session.flush()
    return call


@pytest.mark.asyncio
async def test_call_analysis_pipeline_happy_path(db_session: AsyncSession) -> None:
    org_id = "org_test_pipeline_1"
    call_id = "call_pipe_1"
    call = await _setup_test_call_data(db_session, org_id, call_id)

    fake_llm = FakeLLMProvider(
        responses={
            "call_analysis": {
                "intentDetected": "faq",
                "sentiment": "positive",
                "resolutionStatus": "resolved",
                "summary": "Customer requested password reset. Agent resolved issue.",
                "keyTopics": ["password reset", "account access"],
                "customFields": {"customerRating": 5},
            }
        }
    )

    def mock_webhook_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "received"})

    transport = httpx.MockTransport(mock_webhook_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        analysis = await run_call_analysis_pipeline(
            db_session,
            org_id,
            call_id,
            llm_provider=fake_llm,
            http_client=http_client,
        )

    assert analysis.intent_detected == "faq"
    assert analysis.sentiment == "positive"
    assert analysis.summary == "Customer requested password reset. Agent resolved issue."
    assert call.intent == "faq"
    assert call.outcome == "resolved"

    # Verify Usage Record
    usage_repo = CallUsageRepository(db_session)
    usage = await usage_repo.get_by_call_id(org_id, call_id)
    assert usage is not None
    assert usage.stt_seconds == 120
    assert usage.estimated_cost > 0


@pytest.mark.asyncio
async def test_call_analysis_pipeline_retry_resumability(db_session: AsyncSession) -> None:
    """Verify that re-invoking the pipeline after initial completion does not re-compute
    or crash.
    """
    org_id = "org_test_pipeline_2"
    call_id = "call_pipe_2"
    await _setup_test_call_data(db_session, org_id, call_id)

    fake_llm = FakeLLMProvider(
        responses={
            "call_analysis": {
                "intentDetected": "booking",
                "sentiment": "neutral",
                "resolutionStatus": "booked",
                "summary": "Appointment scheduled.",
                "keyTopics": ["booking"],
                "customFields": {},
            }
        }
    )

    # First run
    await run_call_analysis_pipeline(db_session, org_id, call_id, llm_provider=fake_llm)

    # Second run (retry/replay)
    analysis_repo = CallAnalysisRepository(db_session)
    analysis_second = await run_call_analysis_pipeline(
        db_session, org_id, call_id, llm_provider=fake_llm
    )
    assert analysis_second.intent_detected == "booking"

    count = len(await analysis_repo.list_for_organization(org_id))
    assert count == 1
