"""RQ entry point for generating the structured screening result once a
call's transcript is finalized. Enqueued by the HR screening agent process
(app.ai_employees.hr.runtime.screening_agent) when a call ends — kept as a
separate queued step (rather than running inline in the agent process) so
the agent process can shut down promptly after a call finishes.
"""

from __future__ import annotations

import asyncio

from app.ai_employees.hr.models.candidate import CANDIDATE_TRANSITIONS, CandidateStage
from app.ai_employees.hr.models.screening import ScreeningStatus
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.workflows.screening_result_pipeline import generate_screening_result
from app.core.logging import get_logger
from app.shared.database.session import dispose_engine, get_session_factory
from app.workers.queue.rq_client import get_queue

logger = get_logger(__name__)


def enqueue_screening_result(*, organization_id: str, screening_id: str) -> None:
    get_queue().enqueue(
        process_screening_result_job,
        organization_id,
        screening_id,
        job_timeout=300,
        retry=None,
    )


def process_screening_result_job(organization_id: str, screening_id: str) -> None:
    asyncio.run(_process_screening_result_async(organization_id, screening_id))


async def _process_screening_result_async(organization_id: str, screening_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            screening = await generate_screening_result(
                session, organization_id=organization_id, screening_id=screening_id
            )

            if screening.status == ScreeningStatus.COMPLETED:
                candidate_repo = CandidateRepository(session)
                candidate = await candidate_repo.get_by_id(organization_id, screening.candidate_id)
                if candidate is not None and CANDIDATE_TRANSITIONS.can_transition(
                    candidate.stage, CandidateStage.SCREENED
                ):
                    candidate.stage = CandidateStage.SCREENED
                    # A completed screening is immediately ready for HR's
                    # human-review Gate 2 decision — there is no separate
                    # manual "submit for review" action anywhere in the
                    # product, so advance straight through here too (this is
                    # the real automated call-completion path; see the same
                    # fix in ScreeningService.complete_screening/generate_result
                    # for the manual API routes).
                    if CANDIDATE_TRANSITIONS.can_transition(
                        candidate.stage, CandidateStage.HUMAN_REVIEW
                    ):
                        candidate.stage = CandidateStage.HUMAN_REVIEW

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("screening_result_job_crashed", screening_id=screening_id)
            raise
        finally:
            await dispose_engine()
