"""RQ entry point for knowledge ingestion/re-indexing — same shape as
app.workers.jobs.hr_resume_jobs.
"""

from __future__ import annotations

import asyncio

import redis
from rq import Queue

from app.core.config import get_settings
from app.core.logging import get_logger
from app.knowledge.workflows.ingestion_pipeline import run_ingestion_pipeline
from app.shared.database.session import dispose_engine, get_session_factory

logger = get_logger(__name__)

_queue: Queue | None = None


def _get_knowledge_queue() -> Queue:
    global _queue
    if _queue is None:
        connection = redis.Redis.from_url(get_settings().redis_url)
        _queue = Queue("knowledge", connection=connection)
    return _queue


def enqueue_ingestion(*, organization_id: str, source_version_id: str) -> None:
    _get_knowledge_queue().enqueue(
        process_ingestion_job, organization_id, source_version_id, job_timeout=600, retry=None
    )


def process_ingestion_job(organization_id: str, source_version_id: str) -> None:
    asyncio.run(_process_ingestion_async(organization_id, source_version_id))


async def _process_ingestion_async(organization_id: str, source_version_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await run_ingestion_pipeline(
                session, organization_id=organization_id, source_version_id=source_version_id
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "ingestion_job_crashed",
                organization_id=organization_id,
                source_version_id=source_version_id,
            )
            raise
        finally:
            await dispose_engine()
