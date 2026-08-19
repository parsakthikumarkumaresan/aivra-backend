from __future__ import annotations

import asyncio

from app.ai_employees.voice.workflows.call_analysis_pipeline import run_call_analysis_pipeline
from app.core.logging import get_logger
from app.shared.database.session import dispose_engine, get_session_factory
from app.workers.queue.rq_client import get_queue

logger = get_logger(__name__)


def enqueue_post_call_analysis(organization_id: str, call_id: str) -> None:
    try:
        get_queue().enqueue(
            process_post_call_analysis_job,
            organization_id,
            call_id,
            job_timeout=300,
            retry=None,
        )
    except Exception as exc:
        logger.warning(f"Could not enqueue voice job to Redis RQ: {exc}")


def process_post_call_analysis_job(organization_id: str, call_id: str) -> None:
    asyncio.run(_process_post_call_analysis_async(organization_id, call_id))


async def _process_post_call_analysis_async(organization_id: str, call_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await run_call_analysis_pipeline(
                session, organization_id=organization_id, call_id=call_id
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "post_call_analysis_job_crashed",
                organization_id=organization_id,
                call_id=call_id,
            )
            raise
        finally:
            await dispose_engine()
