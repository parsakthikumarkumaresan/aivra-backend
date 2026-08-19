from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.call import CallIntent, CallOutcome
from app.ai_employees.voice.models.call_analysis import CallAnalysis
from app.ai_employees.voice.models.call_usage import CallUsage
from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.call_analysis_repository import CallAnalysisRepository
from app.ai_employees.voice.repositories.call_repository import CallRepository, TranscriptRepository
from app.ai_employees.voice.repositories.call_usage_repository import CallUsageRepository
from app.ai_employees.voice.repositories.tool_execution_repository import ToolExecutionRepository
from app.ai_employees.voice.repositories.tool_repository import ToolRepository
from app.ai_employees.voice.runtime.llm_provider import get_voice_llm_provider
from app.ai_employees.voice.schemas.analysis import (
    CALL_ANALYSIS_RESULT_JSON_SCHEMA,
    MODEL_VERSION,
    PROMPT_VERSION,
    CallAnalysisResult,
)
from app.ai_employees.voice.services.tool_execution_service import ToolExecutionService
from app.shared.ai_providers.llm import LLMProvider
from app.shared.errors.exceptions import NotFoundError

logger = logging.getLogger(__name__)


async def run_call_analysis_pipeline(
    session: AsyncSession,
    organization_id: str,
    call_id: str,
    llm_provider: LLMProvider | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> CallAnalysis:
    """Resumable multi-stage pipeline for Voice post-call processing (spec section 10.1).

    Stages:
    1. EXTRACT_ANALYSIS: Structured analysis via OpenAI extract_structured.
    2. RECORD_USAGE: Token counts and cost calculation into CallUsage.
    3. EXECUTE_ACTIONS: Webhooks and configured tool triggers.
    """
    call_repo = CallRepository(session)
    transcript_repo = TranscriptRepository(session)
    analysis_repo = CallAnalysisRepository(session)
    usage_repo = CallUsageRepository(session)
    version_repo = AgentVersionRepository(session)

    call = await call_repo.get_by_id(organization_id, call_id)
    if call is None:
        raise NotFoundError("Call not found.")

    version = await version_repo.get_by_id(organization_id, call.agent_version_id)
    if version is None:
        raise NotFoundError("AgentVersion not found for call.")

    # -------------------------------------------------------------------------
    # STAGE 1: EXTRACT_ANALYSIS
    # -------------------------------------------------------------------------
    analysis = await analysis_repo.get_by_call_id(organization_id, call_id)
    if analysis is None:
        transcript = await transcript_repo.get_by_call_id(organization_id, call_id)
        turns = transcript.turns if transcript else []
        formatted_turns = "\n".join(
            f"{t.get('speaker', 'unknown')}: {t.get('text', '')}" for t in turns
        )

        system_prompt = (
            "Analyze the following call transcript and produce a structured summary. "
            f"Custom Fields Config: {version.analysis_config.get('customFields', [])}"
        )
        user_content = f"TRANSCRIPT:\n{formatted_turns or 'No conversation recorded.'}"

        provider = llm_provider or get_voice_llm_provider()
        structured_raw = await provider.extract_structured(
            system_prompt=system_prompt,
            user_content=user_content,
            json_schema=CALL_ANALYSIS_RESULT_JSON_SCHEMA,
            schema_name="call_analysis",
        )

        # Hand-written Pydantic re-validation
        result = CallAnalysisResult.model_validate(structured_raw)

        analysis = CallAnalysis(
            organization_id=organization_id,
            call_id=call_id,
            intent_detected=result.intent_detected,
            sentiment=result.sentiment,
            resolution_status=result.resolution_status,
            summary=result.summary,
            key_topics=result.key_topics,
            custom_fields=result.custom_fields,
            model_version=MODEL_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        analysis = await analysis_repo.add(analysis)

        # Update denormalized summary, intent, outcome on Call
        call.summary = result.summary
        if result.intent_detected and result.intent_detected in CallIntent.__members__.values():
            call.intent = CallIntent(result.intent_detected)
        if (
            result.resolution_status
            and result.resolution_status in CallOutcome.__members__.values()
        ):
            call.outcome = CallOutcome(result.resolution_status)

        await session.flush()

    # -------------------------------------------------------------------------
    # STAGE 2: RECORD_USAGE
    # -------------------------------------------------------------------------
    usage = await usage_repo.get_by_call_id(organization_id, call_id)
    if usage is None:
        # Estimated token metrics
        prompt_tokens = 250
        completion_tokens = 150
        total_tokens = prompt_tokens + completion_tokens
        stt_sec = call.duration_seconds
        telephony_min = max(1, (call.duration_seconds + 59) // 60)
        cost = (total_tokens * 0.000002) + (stt_sec * 0.0001) + (telephony_min * 0.015)

        usage = CallUsage(
            organization_id=organization_id,
            call_id=call_id,
            provider="openai",
            model_name=MODEL_VERSION,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            stt_seconds=stt_sec,
            tts_characters=len(call.summary or "") * 4,
            telephony_minutes=telephony_min,
            estimated_cost=round(cost, 4),
        )
        await usage_repo.add(usage)
        await session.flush()

    # -------------------------------------------------------------------------
    # STAGE 3: EXECUTE_ACTIONS
    # -------------------------------------------------------------------------
    call_end_config = version.call_end_config or {}
    webhook_url = call_end_config.get("webhookUrl")
    if webhook_url and webhook_url.startswith(("http://", "https://")):
        client_provided = http_client is not None
        client = http_client or httpx.AsyncClient(timeout=10.0)
        try:
            payload = {
                "callId": call_id,
                "summary": analysis.summary,
                "intent": analysis.intent_detected,
                "sentiment": analysis.sentiment,
                "resolution": analysis.resolution_status,
                "durationSeconds": call.duration_seconds,
            }
            await client.post(webhook_url, json=payload)
        except Exception as exc:
            logger.warning(f"Failed to post call end webhook to {webhook_url}: {exc}")
        finally:
            if not client_provided:
                await client.aclose()

    # Tool triggers execution
    tool_ids = version.tool_ids or []
    if tool_ids:
        tool_repo = ToolRepository(session)
        exec_repo = ToolExecutionRepository(session)
        exec_service = ToolExecutionService(tool_repo, exec_repo, http_client=http_client)
        for tool_id in tool_ids:
            try:
                await exec_service.execute_tool(
                    organization_id,
                    call_id,
                    tool_id,
                    input_data={"callSummary": analysis.summary},
                )
            except Exception as exc:
                logger.warning(f"Post-call tool execution error for tool {tool_id}: {exc}")

    return analysis
