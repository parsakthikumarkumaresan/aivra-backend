from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.integrations.factory import get_calendar_provider
from app.ai_employees.hr.models.candidate import CandidateStage
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.integration_repository import IntegrationRepository
from app.ai_employees.hr.repositories.interview_repository import InterviewRepository
from app.ai_employees.hr.repositories.schedule_slot_repository import ScheduleSlotRepository
from app.ai_employees.hr.schemas.candidate import CandidateDecisionRequest, CandidateResponse
from app.ai_employees.hr.services.candidate_service import CandidateService
from app.ai_employees.hr.services.scheduling_service import SchedulingService
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.shared.database.session import get_db
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/hr/candidates", tags=["hr-candidates"])


def _service(db: AsyncSession = Depends(get_db)) -> CandidateService:
    return CandidateService(CandidateRepository(db), AuditService(AuditRepository(db)))


def _scheduling_service(db: AsyncSession = Depends(get_db)) -> SchedulingService:
    return SchedulingService(
        InterviewRepository(db),
        ScheduleSlotRepository(db),
        CandidateRepository(db),
        IntegrationRepository(db),
        get_calendar_provider(),
    )


@router.get("", response_model=list[CandidateResponse])
async def list_candidates(
    job_id: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    search: str | None = None,
    auth: AuthContext = Depends(require_hr_active),
    service: CandidateService = Depends(_service),
) -> list[CandidateResponse]:
    candidates = await service.list_candidates(
        auth.require_organization_id(),
        job_id=job_id,
        stage=CandidateStage(stage) if stage else None,
        source=source,
        search=search,
    )
    return [CandidateResponse.model_validate(c) for c in candidates]


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    service: CandidateService = Depends(_service),
) -> CandidateResponse:
    candidate = await service.get_candidate(auth.require_organization_id(), candidate_id)
    return CandidateResponse.model_validate(candidate)


@router.post("/{candidate_id}/approve-for-screening", response_model=CandidateResponse)
async def approve_for_screening(
    candidate_id: str,
    _payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
) -> CandidateResponse:
    candidate = await service.approve_for_screening(
        auth.require_organization_id(), candidate_id, actor_id=auth.user.id
    )
    return CandidateResponse.model_validate(candidate)


@router.post("/{candidate_id}/reject", response_model=CandidateResponse)
async def reject_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
) -> CandidateResponse:
    candidate = await service.reject(
        auth.require_organization_id(), candidate_id, actor_id=auth.user.id, reason=payload.note
    )
    return CandidateResponse.model_validate(candidate)


@router.post("/{candidate_id}/hold", response_model=CandidateResponse)
async def hold_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
) -> CandidateResponse:
    candidate = await service.hold(
        auth.require_organization_id(), candidate_id, actor_id=auth.user.id, reason=payload.note
    )
    return CandidateResponse.model_validate(candidate)


@router.post("/{candidate_id}/approve-for-interview", response_model=CandidateResponse)
async def approve_for_interview(
    candidate_id: str,
    _payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    scheduling: SchedulingService = Depends(_scheduling_service),
) -> CandidateResponse:
    candidate = await service.approve_for_interview(
        auth.require_organization_id(), candidate_id, actor_id=auth.user.id
    )
    await scheduling.request_interview(auth.require_organization_id(), candidate_id)
    return CandidateResponse.model_validate(candidate)
