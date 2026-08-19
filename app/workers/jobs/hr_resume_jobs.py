"""RQ entry point for the resume pipeline.

RQ jobs are plain synchronous callables (they run in a separate worker
process, started via ``python -m app.workers.worker``); the async pipeline
is driven with ``asyncio.run`` inside that process. Each job run opens and
disposes its own DB engine — worker processes are short-lived per job by
RQ's design, so there is no cross-job event-loop reuse hazard here (unlike
the pytest case documented in tests/conftest.py).
"""

from __future__ import annotations

import asyncio

from app.ai_employees.hr.workflows.resume_pipeline import run_resume_pipeline
from app.core.logging import get_logger
from app.shared.database.session import dispose_engine, get_session_factory
from app.workers.queue.rq_client import get_queue

logger = get_logger(__name__)


def enqueue_resume_processing(*, organization_id: str, resume_id: str) -> None:
    get_queue().enqueue(
        process_resume_job,
        organization_id,
        resume_id,
        job_timeout=300,
        retry=None,
    )


def process_resume_job(organization_id: str, resume_id: str) -> None:
    asyncio.run(_process_resume_async(organization_id, resume_id))


async def _process_resume_async(organization_id: str, resume_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await run_resume_pipeline(session, organization_id=organization_id, resume_id=resume_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "resume_pipeline_job_crashed", organization_id=organization_id, resume_id=resume_id
            )
            raise
        finally:
            await dispose_engine()
