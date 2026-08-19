from __future__ import annotations

from livekit.agents import AgentSession, AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.plugins import openai

from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.core.config import get_settings
from app.core.logging import get_logger
from app.knowledge.repositories.document_chunk_repository import DocumentChunkRepository
from app.knowledge.repositories.source_repository import SourceRepository
from app.knowledge.services.retrieval_service import RetrievalService
from app.shared.ai_providers.factory import get_embedding_provider
from app.shared.database.session import get_session_factory

logger = get_logger(__name__)


class VoiceAgentWorker:
    """LiveKit Agents Worker process (spec sections 11, 21; ADR 0002).

    Drives real-time conversational loops over WebRTC/LiveKit rooms.
    """

    def __init__(self) -> None:
        self.session_factory = get_session_factory()

    async def entrypoint(self, ctx: JobContext) -> None:
        logger.info(f"Connecting to LiveKit room: {ctx.room.name}")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        metadata = ctx.room.metadata or ""
        agent_version_id = metadata if metadata.startswith("aver_") else None

        system_prompt = "You are a professional AI Voice Employee powered by AIVRA."
        knowledge_ids: list[str] = []

        if agent_version_id:
            async with self.session_factory() as session:
                version_repo = AgentVersionRepository(session)
                stmt_version = await version_repo.get_by_id("system", agent_version_id)
                if stmt_version:
                    system_prompt = stmt_version.prompt_config.get(
                        "systemPrompt", system_prompt
                    )
                    knowledge_ids = stmt_version.library.get("knowledgeSourceIds", [])

        # RAG Knowledge Grounding
        rag_context = ""
        if knowledge_ids:
            async with self.session_factory() as session:
                source_repo = SourceRepository(session)
                chunk_repo = DocumentChunkRepository(session)
                embedding_provider = get_embedding_provider()
                retrieval_service = RetrievalService(source_repo, chunk_repo, embedding_provider)

                org_id = ctx.room.name.split("_")[1] if "_" in ctx.room.name else ""
                chunks = await retrieval_service.retrieve(
                    organization_id=org_id,
                    employee_type="voice",
                    query=system_prompt,
                    limit=3,
                )
                if chunks:
                    rag_context = "\n".join([c.content for c in chunks])
                    system_prompt += f"\n\nKNOWLEDGE CONTEXT:\n{rag_context}"

        # Initialize OpenAI LLM
        llm_model = get_settings().voice_llm_model or "gpt-4o-mini"
        model_instance = openai.LLM(model=llm_model)

        session_agent: AgentSession = AgentSession(llm=model_instance)
        logger.info(
            f"Voice Agent active in room {ctx.room.name} with model {llm_model} "
            f"(session: {session_agent})"
        )


def main() -> None:
    worker = VoiceAgentWorker()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=worker.entrypoint,
        )
    )


if __name__ == "__main__":
    main()
