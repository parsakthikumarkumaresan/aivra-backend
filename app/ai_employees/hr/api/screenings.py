from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.models.screening import Screening
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.schemas.screening import (
    CompleteScreeningRequest,
    ScreeningPromptResponse,
    ScreeningResponse,
    UpdateScreeningPromptRequest,
)
from app.ai_employees.hr.services.screening_service import ScreeningService
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.core.logging import get_logger
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext
from app.workers.jobs.hr_screening_jobs import enqueue_screening_call

router = APIRouter(prefix="/hr/screenings", tags=["hr-screenings"])
logger = get_logger(__name__)


def _service(db: AsyncSession = Depends(get_db)) -> ScreeningService:
    return ScreeningService(
        ScreeningRepository(db),
        CandidateRepository(db),
        CandidateIdentityRepository(db),
        AuditService(AuditRepository(db)),
    )


def _to_prompt_response(screening: Screening) -> ScreeningPromptResponse:
    return ScreeningPromptResponse(
        candidate_id=screening.candidate_id,
        prompt_text=screening.prompt_text or "",
        prompt_generated_at=screening.prompt_generated_at,
        prompt_edited_at=screening.prompt_edited_at,
    )


@router.get("", response_model=list[ScreeningResponse])
async def list_screenings(
    auth: AuthContext = Depends(require_hr_active), service: ScreeningService = Depends(_service)
) -> list[ScreeningResponse]:
    screenings = await service.list_all(auth.require_organization_id())
    return [ScreeningResponse.model_validate(s) for s in screenings]


@router.get("/candidates/{candidate_id}/prompt", response_model=ScreeningPromptResponse)
async def get_screening_prompt(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    service: ScreeningService = Depends(_service),
) -> ScreeningPromptResponse:
    """Generates the prompt on first call (lazy, spec section 4) and simply
    returns it on subsequent calls — never regenerates over an HR edit.
    """
    screening = await service.get_or_generate_prompt(auth.require_organization_id(), candidate_id)
    return _to_prompt_response(screening)


@router.patch("/candidates/{candidate_id}/prompt", response_model=ScreeningPromptResponse)
async def update_screening_prompt(
    candidate_id: str,
    payload: UpdateScreeningPromptRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: ScreeningService = Depends(_service),
) -> ScreeningPromptResponse:
    screening = await service.update_prompt(
        auth.require_organization_id(),
        candidate_id,
        prompt_text=payload.prompt_text,
        actor_id=auth.user.id,
    )
    return _to_prompt_response(screening)


@router.post("/candidates/{candidate_id}/start", response_model=ScreeningResponse, status_code=201)
async def start_screening(
    candidate_id: str,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: ScreeningService = Depends(_service),
) -> ScreeningResponse:
    organization_id = auth.require_organization_id()
    logger.info("SCREENING_START", organization_id=organization_id, candidate_id=candidate_id)
    screening = await service.start_screening(organization_id, candidate_id, actor_id=auth.user.id)

    # Enqueued via BackgroundTasks (runs after the response — and after the
    # request's DB commit — completes), matching resumes.py's pattern, so
    # the LiveKit call is never placed against a not-yet-committed screening.
    background_tasks.add_task(
        enqueue_screening_call, organization_id=organization_id, screening_id=screening.id
    )
    return ScreeningResponse.model_validate(screening)


@router.post("/candidates/{candidate_id}/generate-result", response_model=ScreeningResponse)
async def generate_screening_result_route(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: ScreeningService = Depends(_service),
) -> ScreeningResponse:
    """Defensive manual-recovery endpoint (spec section 12) — see
    ScreeningService.generate_result docstring.
    """
    screening = await service.generate_result(auth.require_organization_id(), candidate_id)
    return ScreeningResponse.model_validate(screening)


@router.post("/candidates/{candidate_id}/complete", response_model=ScreeningResponse)
async def complete_screening(
    candidate_id: str,
    payload: CompleteScreeningRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: ScreeningService = Depends(_service),
) -> ScreeningResponse:
    screening = await service.complete_screening(
        auth.require_organization_id(), candidate_id, result_summary=payload.result_summary
    )
    return ScreeningResponse.model_validate(screening)


@router.get("/candidates/{candidate_id}", response_model=ScreeningResponse)
async def get_candidate_screening(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    service: ScreeningService = Depends(_service),
) -> ScreeningResponse:
    screening = await service.get_for_candidate(auth.require_organization_id(), candidate_id)
    if screening is None:
        raise NotFoundError("No screening exists for this candidate.")
    return ScreeningResponse.model_validate(screening)
