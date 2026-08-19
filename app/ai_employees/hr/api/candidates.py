from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.integrations.factory import get_calendar_provider
from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import (
    CandidateRepository,
    CandidateVisibility,
)
from app.ai_employees.hr.repositories.integration_repository import IntegrationRepository
from app.ai_employees.hr.repositories.interview_repository import InterviewRepository
from app.ai_employees.hr.repositories.schedule_slot_repository import ScheduleSlotRepository
from app.ai_employees.hr.schemas.candidate import (
    BulkArchiveRequest,
    BulkArchiveResponse,
    CandidateDecisionRequest,
    CandidateResponse,
    UpdateCandidateIdentityRequest,
)
from app.ai_employees.hr.services.candidate_service import CandidateService
from app.ai_employees.hr.services.scheduling_service import SchedulingService
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/hr/candidates", tags=["hr-candidates"])


def _service(db: AsyncSession = Depends(get_db)) -> CandidateService:
    return CandidateService(
        CandidateRepository(db), CandidateIdentityRepository(db), AuditService(AuditRepository(db))
    )


def _identity_repo(db: AsyncSession = Depends(get_db)) -> CandidateIdentityRepository:
    return CandidateIdentityRepository(db)


def _scheduling_service(db: AsyncSession = Depends(get_db)) -> SchedulingService:
    return SchedulingService(
        InterviewRepository(db),
        ScheduleSlotRepository(db),
        CandidateRepository(db),
        CandidateIdentityRepository(db),
        IntegrationRepository(db),
        get_calendar_provider(),
    )


def to_candidate_response(candidate: Candidate, identity: CandidateIdentity) -> CandidateResponse:
    """Flattens the Candidate (per-job application) + CandidateIdentity
    (person) split back into the single API-visible "candidate" resource —
    used here and by app.ai_employees.hr.api.resumes so both routers build
    an identical response shape.
    """
    return CandidateResponse(
        id=candidate.id,
        identity_id=identity.id,
        job_id=candidate.job_id,
        full_name=identity.full_name,
        email=identity.email,
        phone=identity.phone,
        source=candidate.source,
        stage=candidate.stage,
        resume_id=candidate.resume_id,
        rejected_reason=candidate.rejected_reason,
        archived_at=candidate.archived_at,
        archived_by_user_id=candidate.archived_by_user_id,
    )


async def _to_response_with_identity(
    candidate: Candidate, identity_repo: CandidateIdentityRepository, organization_id: str
) -> CandidateResponse:
    identity = await identity_repo.get_by_id(organization_id, candidate.identity_id)
    if identity is None:
        raise NotFoundError("Candidate identity not found.")
    return to_candidate_response(candidate, identity)


@router.get("", response_model=list[CandidateResponse])
async def list_candidates(
    job_id: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    search: str | None = None,
    status: CandidateVisibility = "active",
    auth: AuthContext = Depends(require_hr_active),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> list[CandidateResponse]:
    organization_id = auth.require_organization_id()
    candidates = await service.list_candidates(
        organization_id,
        job_id=job_id,
        stage=CandidateStage(stage) if stage else None,
        source=source,
        search=search,
        visibility=status,
    )
    identities = await identity_repo.list_by_ids(
        organization_id, [c.identity_id for c in candidates]
    )
    return [
        to_candidate_response(c, identities[c.identity_id])
        for c in candidates
        if c.identity_id in identities
    ]


@router.post("/archive", response_model=BulkArchiveResponse)
async def bulk_archive_candidates(
    payload: BulkArchiveRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> BulkArchiveResponse:
    organization_id = auth.require_organization_id()
    archived, skipped = await service.bulk_archive(
        organization_id, payload.candidate_ids, actor_id=auth.user.id
    )
    identities = await identity_repo.list_by_ids(organization_id, [c.identity_id for c in archived])
    return BulkArchiveResponse(
        archived=[
            to_candidate_response(c, identities[c.identity_id])
            for c in archived
            if c.identity_id in identities
        ],
        skipped=skipped,
    )


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.get_candidate(organization_id, candidate_id)
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.patch("/{candidate_id}", response_model=CandidateResponse)
async def update_candidate_identity(
    candidate_id: str,
    payload: UpdateCandidateIdentityRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.update_identity(
        organization_id,
        candidate_id,
        actor_id=auth.user.id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
    )
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/approve-for-screening", response_model=CandidateResponse)
async def approve_for_screening(
    candidate_id: str,
    _payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.approve_for_screening(
        organization_id, candidate_id, actor_id=auth.user.id
    )
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/reject", response_model=CandidateResponse)
async def reject_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.reject(
        organization_id, candidate_id, actor_id=auth.user.id, reason=payload.note
    )
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/hold", response_model=CandidateResponse)
async def hold_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.hold(
        organization_id, candidate_id, actor_id=auth.user.id, reason=payload.note
    )
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/approve-for-interview", response_model=CandidateResponse)
async def approve_for_interview(
    candidate_id: str,
    _payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
    scheduling: SchedulingService = Depends(_scheduling_service),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.approve_for_interview(
        organization_id, candidate_id, actor_id=auth.user.id
    )
    await scheduling.request_interview(organization_id, candidate_id)
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/reconsider", response_model=CandidateResponse)
async def reconsider_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    """Explicit human action moving a REJECTED application back to
    HR_REVIEW. Never triggered automatically by resume re-upload.
    """
    organization_id = auth.require_organization_id()
    candidate = await service.reconsider(
        organization_id, candidate_id, actor_id=auth.user.id, note=payload.note
    )
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/archive", response_model=CandidateResponse)
async def archive_candidate(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.archive(organization_id, candidate_id, actor_id=auth.user.id)
    return await _to_response_with_identity(candidate, identity_repo, organization_id)


@router.post("/{candidate_id}/restore", response_model=CandidateResponse)
async def restore_candidate(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: CandidateService = Depends(_service),
    identity_repo: CandidateIdentityRepository = Depends(_identity_repo),
) -> CandidateResponse:
    organization_id = auth.require_organization_id()
    candidate = await service.restore(organization_id, candidate_id, actor_id=auth.user.id)
    return await _to_response_with_identity(candidate, identity_repo, organization_id)
