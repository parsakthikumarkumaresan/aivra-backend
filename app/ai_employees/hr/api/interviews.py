from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.integrations.factory import get_calendar_provider
from app.ai_employees.hr.models.interview import Interview
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.integration_repository import IntegrationRepository
from app.ai_employees.hr.repositories.interview_panelist_repository import (
    InterviewPanelistRepository,
)
from app.ai_employees.hr.repositories.interview_repository import InterviewRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.schedule_slot_repository import ScheduleSlotRepository
from app.ai_employees.hr.schemas.interview import (
    BookSlotRequest,
    CalendarStatusResponse,
    CompleteInterviewRequest,
    CreateSlotRequest,
    InterviewPanelistResponse,
    InterviewResponse,
    ScheduleSlotResponse,
)
from app.ai_employees.hr.services.scheduling_service import SchedulingService
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.notifications.factory import get_email_sender
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
        InterviewPanelistRepository(db),
        get_email_sender(),
        AuditService(AuditRepository(db)),
    )


def _job_repo(db: AsyncSession = Depends(get_db)) -> JobRepository:
    return JobRepository(db)


def _panelist_repo(db: AsyncSession = Depends(get_db)) -> InterviewPanelistRepository:
    return InterviewPanelistRepository(db)


def _slot_repo(db: AsyncSession = Depends(get_db)) -> ScheduleSlotRepository:
    return ScheduleSlotRepository(db)


async def _to_interview_response(
    interview: Interview,
    panelist_repo: InterviewPanelistRepository,
    organization_id: str,
    slot_repo: ScheduleSlotRepository | None = None,
) -> InterviewResponse:
    panelists = await panelist_repo.list_for_interview(organization_id, interview.id)
    response = InterviewResponse.model_validate(interview)
    response.panelists = [
        InterviewPanelistResponse(email=p.email, name=p.name, notified_at=p.notified_at)
        for p in panelists
    ]
    if slot_repo is not None and interview.scheduled_slot_id:
        slot = await slot_repo.get_by_id(organization_id, interview.scheduled_slot_id)
        if slot is not None:
            response.scheduled_start_time = slot.start_time
            response.scheduled_end_time = slot.end_time
    return response


@router.get("/interviews", response_model=list[InterviewResponse])
async def list_interviews(
    auth: AuthContext = Depends(require_hr_active),
    db: AsyncSession = Depends(get_db),
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
    slot_repo: ScheduleSlotRepository = Depends(_slot_repo),
) -> list[InterviewResponse]:
    organization_id = auth.require_organization_id()
    interviews = await InterviewRepository(db).list_all(organization_id)
    return [
        await _to_interview_response(i, panelist_repo, organization_id, slot_repo)
        for i in interviews
    ]


@router.get("/candidates/{candidate_id}/interview", response_model=InterviewResponse)
async def get_candidate_interview(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    db: AsyncSession = Depends(get_db),
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
    slot_repo: ScheduleSlotRepository = Depends(_slot_repo),
) -> InterviewResponse:
    organization_id = auth.require_organization_id()
    interview = await InterviewRepository(db).get_for_candidate(organization_id, candidate_id)
    if interview is None:
        raise NotFoundError("No interview exists for this candidate.")
    return await _to_interview_response(interview, panelist_repo, organization_id, slot_repo)


@router.post("/interviews/{interview_id}/approve", response_model=InterviewResponse)
async def approve_interview(
    interview_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
) -> InterviewResponse:
    organization_id = auth.require_organization_id()
    interview = await service.approve_interview(organization_id, interview_id)
    return await _to_interview_response(interview, panelist_repo, organization_id)


@router.post("/interviews/{interview_id}/complete", response_model=InterviewResponse)
async def complete_interview(
    interview_id: str,
    payload: CompleteInterviewRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
) -> InterviewResponse:
    organization_id = auth.require_organization_id()
    interview = await service.complete_interview(organization_id, interview_id, notes=payload.notes)
    return await _to_interview_response(interview, panelist_repo, organization_id)


@router.post("/interviews/{interview_id}/cancel", response_model=InterviewResponse)
async def cancel_interview(
    interview_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
) -> InterviewResponse:
    organization_id = auth.require_organization_id()
    interview = await service.cancel_interview(organization_id, interview_id)
    return await _to_interview_response(interview, panelist_repo, organization_id)


@router.get("/scheduling/availability", response_model=list[ScheduleSlotResponse])
async def list_available_slots(
    auth: AuthContext = Depends(require_hr_active), service: SchedulingService = Depends(_service)
) -> list[ScheduleSlotResponse]:
    slots = await service.list_available_slots(auth.require_organization_id())
    return [ScheduleSlotResponse.model_validate(s) for s in slots]


@router.get("/scheduling/calendar-status", response_model=CalendarStatusResponse)
async def calendar_status(
    auth: AuthContext = Depends(require_hr_active), service: SchedulingService = Depends(_service)
) -> CalendarStatusResponse:
    connected = await service.is_calendar_connected(auth.require_organization_id())
    return CalendarStatusResponse(connected=connected)


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
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
    slot_repo: ScheduleSlotRepository = Depends(_slot_repo),
) -> InterviewResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.candidate_repo.get_by_id(organization_id, payload.candidate_id)
    job_title = "Interview"
    company_name = None
    if candidate is not None:
        job = await job_repo.get_by_id(organization_id, candidate.job_id)
        if job is not None:
            job_title = job.title
            company_name = job.company_name

    interview = await service.book_slot(
        organization_id,
        payload.slot_id,
        payload.candidate_id,
        job_title=job_title,
        company_name=company_name,
        panelist_emails=payload.panelist_emails,
    )
    return await _to_interview_response(interview, panelist_repo, organization_id, slot_repo)


@router.post("/interviews/{interview_id}/resend-invitations", response_model=InterviewResponse)
async def resend_invitations(
    interview_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: SchedulingService = Depends(_service),
    job_repo: JobRepository = Depends(_job_repo),
    panelist_repo: InterviewPanelistRepository = Depends(_panelist_repo),
    slot_repo: ScheduleSlotRepository = Depends(_slot_repo),
) -> InterviewResponse:
    organization_id = auth.require_organization_id()
    interview = await service.interview_repo.get_by_id(organization_id, interview_id)
    if interview is None:
        raise NotFoundError("Interview not found.")

    job_title = "Interview"
    company_name = None
    candidate = await service.candidate_repo.get_by_id(organization_id, interview.candidate_id)
    if candidate is not None:
        job = await job_repo.get_by_id(organization_id, candidate.job_id)
        if job is not None:
            job_title = job.title
            company_name = job.company_name

    updated_interview = await service.resend_invitations(
        organization_id,
        interview_id,
        job_title=job_title,
        company_name=company_name,
    )
    return await _to_interview_response(
        updated_interview, panelist_repo, organization_id, slot_repo
    )
