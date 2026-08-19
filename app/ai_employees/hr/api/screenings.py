from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.schemas.screening import CompleteScreeningRequest, ScreeningResponse
from app.ai_employees.hr.services.screening_service import ScreeningService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/hr/screenings", tags=["hr-screenings"])


def _service(db: AsyncSession = Depends(get_db)) -> ScreeningService:
    return ScreeningService(ScreeningRepository(db), CandidateRepository(db))


@router.get("", response_model=list[ScreeningResponse])
async def list_screenings(
    auth: AuthContext = Depends(require_hr_active), service: ScreeningService = Depends(_service)
) -> list[ScreeningResponse]:
    screenings = await service.list_all(auth.require_organization_id())
    return [ScreeningResponse.model_validate(s) for s in screenings]


@router.post("/candidates/{candidate_id}/start", response_model=ScreeningResponse, status_code=201)
async def start_screening(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: ScreeningService = Depends(_service),
) -> ScreeningResponse:
    screening = await service.start_screening(auth.require_organization_id(), candidate_id)
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
