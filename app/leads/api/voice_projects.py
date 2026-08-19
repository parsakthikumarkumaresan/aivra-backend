"""AIVRA-internal Voice customization project management (spec 10.3, 16).
Every route requires an AIVRA platform role — never a customer role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.leads.models.voice_project import VoiceProjectStatus
from app.leads.repositories.voice_project_repository import VoiceProjectRepository
from app.leads.schemas.voice_project import (
    AddRequirementRequest,
    AssignEngineerRequest,
    AssignOrganizationRequest,
    RequirementResponse,
    TransitionVoiceProjectRequest,
    VoiceProjectResponse,
)
from app.leads.services.voice_project_service import VoiceProjectService
from app.shared.database.session import get_db
from app.shared.rbac.roles import PlatformRole
from app.shared.security.dependencies import require_platform_role

router = APIRouter(
    prefix="/internal/voice-projects",
    tags=["internal-voice-projects"],
    dependencies=[
        Depends(require_platform_role(PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER))
    ],
)


def _service(db: AsyncSession = Depends(get_db)) -> VoiceProjectService:
    return VoiceProjectService(
        VoiceProjectRepository(db),
        CatalogRepository(db),
        ProvisioningService(ProvisionRepository(db)),
    )


@router.get("", response_model=list[VoiceProjectResponse])
async def list_voice_projects(
    service: VoiceProjectService = Depends(_service),
) -> list[VoiceProjectResponse]:
    projects = await service.list_all()
    return [VoiceProjectResponse.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=VoiceProjectResponse)
async def get_voice_project(
    project_id: str, service: VoiceProjectService = Depends(_service)
) -> VoiceProjectResponse:
    project = await service.get(project_id)
    return VoiceProjectResponse.model_validate(project)


@router.post("/{project_id}/assign-organization", response_model=VoiceProjectResponse)
async def assign_organization(
    project_id: str,
    payload: AssignOrganizationRequest,
    service: VoiceProjectService = Depends(_service),
) -> VoiceProjectResponse:
    project = await service.assign_organization(project_id, payload.organization_id)
    return VoiceProjectResponse.model_validate(project)


@router.post("/{project_id}/assign-engineer", response_model=VoiceProjectResponse)
async def assign_engineer(
    project_id: str,
    payload: AssignEngineerRequest,
    service: VoiceProjectService = Depends(_service),
) -> VoiceProjectResponse:
    project = await service.assign_engineer(project_id, payload.engineer_user_id)
    return VoiceProjectResponse.model_validate(project)


@router.post("/{project_id}/requirements", response_model=RequirementResponse, status_code=201)
async def add_requirement(
    project_id: str,
    payload: AddRequirementRequest,
    service: VoiceProjectService = Depends(_service),
) -> RequirementResponse:
    requirement = await service.add_requirement(project_id, payload.key, payload.value)
    return RequirementResponse.model_validate(requirement)


@router.get("/{project_id}/requirements", response_model=list[RequirementResponse])
async def list_requirements(
    project_id: str, service: VoiceProjectService = Depends(_service)
) -> list[RequirementResponse]:
    requirements = await service.list_requirements(project_id)
    return [RequirementResponse.model_validate(r) for r in requirements]


@router.post("/{project_id}/transition", response_model=VoiceProjectResponse)
async def transition_voice_project(
    project_id: str,
    payload: TransitionVoiceProjectRequest,
    service: VoiceProjectService = Depends(_service),
) -> VoiceProjectResponse:
    project = await service.transition(
        project_id,
        VoiceProjectStatus(payload.target_status),
        failure_reason=payload.failure_reason,
    )
    return VoiceProjectResponse.model_validate(project)
