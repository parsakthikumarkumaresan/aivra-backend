"""RQ entry point for placing an HR AI voice screening call.

Same control-flow shape as app.workers.jobs.hr_resume_jobs: a sync
``enqueue_x`` -> sync ``job_fn`` (``asyncio.run``) -> async impl that opens
its own session and disposes its own engine. This is the step that
actually talks to LiveKit — the HTTP request that triggers it
(POST /hr/screenings/candidates/{id}/start) only validates and flips
Screening.status to IN_PROGRESS; placing the real call happens here, after
that transaction has committed (see the route's use of BackgroundTasks).

Structured lifecycle logging (SCREENING_JOB_ENQUEUED -> SCREENING_JOB_STARTED
-> ... -> SCREENING_CALL_PLACED / SCREENING_CALL_FAILED) lets a stuck or
failed call be diagnosed from logs alone — never log API keys/secrets, only
safe identifiers (screening_id, candidate_id, room name, provider ids).

A successfully *dispatched* call (LiveKit accepted the room/agent/SIP
requests) is not the same as a call that actually connects — LiveKit's
agent-dispatch API only queues a job for whichever worker process is
registered under that agent name; if no such process is running, nothing
ever joins the room and the screening silently hangs at IN_PROGRESS
forever with an empty transcript. ``check_screening_call_stall`` is
scheduled a short delay after dispatch specifically to catch and surface
that failure mode honestly instead of leaving it invisible.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.ai_employees.hr.integrations.livekit_screening_provider import (
    LiveKitScreeningConfigurationError,
    SipParticipantError,
    place_screening_call,
)
from app.ai_employees.hr.models.screening import ScreeningStatus
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.services.candidate_identity import normalize_phone_number
from app.core.logging import get_logger
from app.shared.database.session import dispose_engine, get_session_factory
from app.workers.queue.rq_client import get_queue

logger = get_logger(__name__)

# Grace period for the HR screening agent worker (a separate long-running
# process — see app.ai_employees.hr.runtime.screening_agent) to pick up the
# dispatched job and join the room. Generous enough to cover normal
# ring/answer latency without leaving a genuinely stuck call unnoticed.
_STALL_CHECK_DELAY = timedelta(seconds=60)


def enqueue_screening_call(*, organization_id: str, screening_id: str) -> None:
    get_queue().enqueue(
        process_screening_call_job,
        organization_id,
        screening_id,
        job_timeout=300,
        retry=None,
    )
    logger.info(
        "SCREENING_JOB_ENQUEUED", organization_id=organization_id, screening_id=screening_id
    )


def process_screening_call_job(organization_id: str, screening_id: str) -> None:
    asyncio.run(_process_screening_call_async(organization_id, screening_id))


async def _process_screening_call_async(organization_id: str, screening_id: str) -> None:
    logger.info("SCREENING_JOB_STARTED", organization_id=organization_id, screening_id=screening_id)
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            screening_repo = ScreeningRepository(session)
            candidate_repo = CandidateRepository(session)
            identity_repo = CandidateIdentityRepository(session)

            screening = await screening_repo.get_by_id(organization_id, screening_id)
            if screening is None:
                logger.warning("screening_call_job_screening_not_found", screening_id=screening_id)
                return

            candidate = await candidate_repo.get_by_id(organization_id, screening.candidate_id)
            identity = (
                await identity_repo.get_by_id(organization_id, candidate.identity_id)
                if candidate
                else None
            )
            phone_number = normalize_phone_number(identity.phone) if identity else None
            phone_number = phone_number or ""
            if candidate is None or identity is None or not phone_number:
                screening.status = ScreeningStatus.FAILED
                screening.failure_reason = "Candidate or phone number not found at dispatch time."
                await session.commit()
                logger.error(
                    "SCREENING_CALL_FAILED",
                    screening_id=screening_id,
                    stage="candidate_lookup",
                    reason=screening.failure_reason,
                )
                return

            # A bare 10-digit Indian mobile number is auto-normalized to
            # E.164 above (and already normalized at identity-creation time
            # — see candidate_identity.normalize_phone_number). Anything
            # still not in E.164 here is a genuinely ambiguous case (wrong
            # length, non-Indian local format, etc.) where guessing a
            # country code would risk placing a call to the wrong number —
            # fail loudly instead.
            if not phone_number.startswith("+") or not phone_number[1:].isdigit():
                screening.status = ScreeningStatus.FAILED
                screening.failure_reason = (
                    f"Candidate phone number '{phone_number}' is not in E.164 format "
                    "(missing '+' and country code) — refusing to place a call that would "
                    "likely be rejected by the SIP trunk. Update the candidate's phone "
                    "number to include a country code, e.g. +91XXXXXXXXXX."
                )
                await session.commit()
                logger.error(
                    "SCREENING_CALL_FAILED",
                    screening_id=screening_id,
                    stage="phone_format",
                    reason=screening.failure_reason,
                )
                return

            room_name = f"hr-screening-{screening_id}"
            try:
                dispatched = await place_screening_call(
                    room_name=room_name,
                    screening_id=screening_id,
                    organization_id=organization_id,
                    phone_number=phone_number,
                )
            except LiveKitScreeningConfigurationError as exc:
                screening.status = ScreeningStatus.FAILED
                screening.failure_reason = str(exc)
                await session.commit()
                logger.error(
                    "SCREENING_CALL_FAILED",
                    screening_id=screening_id,
                    stage="configuration",
                    reason=str(exc),
                )
                return
            except SipParticipantError as exc:
                screening.status = ScreeningStatus.FAILED
                screening.failure_reason = str(exc)
                await session.commit()
                logger.error(
                    "SCREENING_CALL_FAILED",
                    screening_id=screening_id,
                    stage="sip_participant",
                    reason=str(exc),
                )
                return
            except Exception as exc:  # any other LiveKit/SIP failure is a real, surfaced failure
                screening.status = ScreeningStatus.FAILED
                screening.failure_reason = f"Failed to place outbound call: {exc}"
                await session.commit()
                logger.exception(
                    "SCREENING_CALL_FAILED", screening_id=screening_id, stage="dispatch"
                )
                return

            screening.livekit_room_name = dispatched.room_name
            screening.livekit_dispatch_id = dispatched.dispatch_id
            screening.sip_call_participant_identity = dispatched.sip_participant_identity
            await session.commit()
            logger.info(
                "SCREENING_CALL_PLACED",
                screening_id=screening_id,
                room_name=dispatched.room_name,
                dispatch_id=dispatched.dispatch_id,
            )
        except Exception:
            await session.rollback()
            logger.exception("screening_call_job_crashed", screening_id=screening_id)
            raise
        finally:
            await dispose_engine()

    # Scheduled after the transaction commits — if no agent worker ever
    # joins the room, this is what turns silence into an honest FAILED
    # status instead of an invisible, permanently-stuck IN_PROGRESS row.
    get_queue().enqueue_in(
        _STALL_CHECK_DELAY,
        check_screening_call_stall,
        organization_id,
        screening_id,
        job_timeout=60,
        retry=None,
    )


def check_screening_call_stall(organization_id: str, screening_id: str) -> None:
    asyncio.run(_check_screening_call_stall_async(organization_id, screening_id))


async def _check_screening_call_stall_async(organization_id: str, screening_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            screening_repo = ScreeningRepository(session)
            screening = await screening_repo.get_by_id(organization_id, screening_id)
            if screening is None:
                return
            if screening.status != ScreeningStatus.IN_PROGRESS:
                return  # already completed/failed through the normal path — nothing to do
            if screening.transcript:
                return  # the agent has joined and is producing turns — genuinely still live

            screening.status = ScreeningStatus.FAILED
            screening.failure_reason = (
                "No screening agent joined the call within the expected time. Verify the HR "
                "screening agent worker process (python -m app.ai_employees.hr.runtime."
                "screening_agent start) is running and registered with LiveKit under the "
                "configured HR_SCREENING_AGENT_NAME."
            )
            await session.commit()
            logger.error(
                "SCREENING_CALL_STALLED",
                screening_id=screening_id,
                room_name=screening.livekit_room_name,
                dispatch_id=screening.livekit_dispatch_id,
            )
        except Exception:
            await session.rollback()
            logger.exception("screening_call_stall_check_crashed", screening_id=screening_id)
            raise
        finally:
            await dispose_engine()
