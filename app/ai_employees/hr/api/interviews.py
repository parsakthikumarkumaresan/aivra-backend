from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.integrations.factory import get_calendar_provider
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.integration_repository import IntegrationRepository
from app.ai_employees.hr.repositories.interview_repository import InterviewRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.schedule_slot_repository import ScheduleSlotRepository
from app.ai_employees.hr.schemas.interview import (
    BookSlotRequest,
    CompleteInterviewRequest,
    CreateSlotRequest,
    InterviewResponse,
    ScheduleSlotResponse,
)
from app.ai_employees.hr.services.scheduling_service import SchedulingService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/hr", tags=["hr-interviews"])


def _service(db: AsyncSession = Depends(get_db)) -> SchedulingService:
    return SchedulingService(
        InterviewRepository(db),
        ScheduleSlotRepository(db),
        CandidateRepository(db),
        CandidateIdentityRepository(db),
        IntegrationRepository(db),
        get_calendar_provider(),
    )


def _job_repo(db: AsyncSession = Depends(get_db)) -> JobRepository:
    return JobRepository(db)


@router.get("/interviews", response_model=list[InterviewResponse])
async def list_interviews(
    auth: AuthContext = Depends(require_hr_active),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewResponse]:
    interviews = await InterviewRepository(db).list_all(auth.require_organization_id())
    return [InterviewResponse.model_validate(i) for i in interviews]


@router.get("/candidates/{candidate_id}/interview", response_model=InterviewResponse)
async def get_candidate_interview(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    db: AsyncSession = Depends(get_db),
) -> InterviewResponse:
    interview = await InterviewRepository(db).get_for_candidate(
        auth.require_organization_id(), candidate_id
    )
    if interview is None:
        raise NotFoundError("No interview exists for this candidate.")
    return InterviewResponse.model_validate(interview)


@router.post("/interviews/{interview_id}/approve", response_model=InterviewResponse)
async def approve_interview(
    interview_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
) -> InterviewResponse:
    interview = await service.approve_interview(auth.require_organization_id(), interview_id)
    return InterviewResponse.model_validate(interview)


@router.post("/interviews/{interview_id}/complete", response_model=InterviewResponse)
async def complete_interview(
    interview_id: str,
    payload: CompleteInterviewRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
) -> InterviewResponse:
    interview = await service.complete_interview(
        auth.require_organization_id(), interview_id, notes=payload.notes
    )
    return InterviewResponse.model_validate(interview)


@router.post("/interviews/{interview_id}/cancel", response_model=InterviewResponse)
async def cancel_interview(
    interview_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
) -> InterviewResponse:
    interview = await service.cancel_interview(auth.require_organization_id(), interview_id)
    return InterviewResponse.model_validate(interview)


@router.get("/scheduling/availability", response_model=list[ScheduleSlotResponse])
async def list_available_slots(
    auth: AuthContext = Depends(require_hr_active), service: SchedulingService = Depends(_service)
) -> list[ScheduleSlotResponse]:
    slots = await service.list_available_slots(auth.require_organization_id())
    return [ScheduleSlotResponse.model_validate(s) for s in slots]


@router.post("/scheduling/slots", response_model=ScheduleSlotResponse, status_code=201)
async def create_slot(
    payload: CreateSlotRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
) -> ScheduleSlotResponse:
    slot = await service.create_slot(
        auth.require_organization_id(),
        payload.interviewer_user_id,
        payload.start_time,
        payload.end_time,
    )
    return ScheduleSlotResponse.model_validate(slot)


@router.post("/scheduling/book", response_model=InterviewResponse)
async def book_slot(
    payload: BookSlotRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
    job_repo: JobRepository = Depends(_job_repo),
) -> InterviewResponse:
    candidate = await service.candidate_repo.get_by_id(
        auth.require_organization_id(), payload.candidate_id
    )
    job_title = "Interview"
    if candidate is not None:
        job = await job_repo.get_by_id(auth.require_organization_id(), candidate.job_id)
        if job is not None:
            job_title = job.title

    interview = await service.book_slot(
        auth.require_organization_id(),
        payload.slot_id,
        payload.candidate_id,
        job_title=job_title,
    )
    return InterviewResponse.model_validate(interview)
