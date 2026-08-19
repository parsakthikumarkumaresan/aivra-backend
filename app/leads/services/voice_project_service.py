"""AIVRA-internal Voice customization project lifecycle (spec sections
10.3, 16). Every transition is AIVRA-role-gated at the API layer — Voice
deployment is explicitly not customer-self-service (spec section 14).
"""

from __future__ import annotations

from app.ai_employees.provisioning.models.provision import ProvisionStatus
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.leads.models.requirement import Requirement
from app.leads.models.voice_project import (
    VOICE_PROJECT_TRANSITIONS,
    VoiceProject,
    VoiceProjectStatus,
)
from app.leads.repositories.voice_project_repository import VoiceProjectRepository
from app.shared.errors.exceptions import ConflictError, NotFoundError


class VoiceProjectService:
    def __init__(
        self,
        project_repo: VoiceProjectRepository,
        catalog_repo: CatalogRepository,
        provisioning: ProvisioningService,
    ) -> None:
        self.project_repo = project_repo
        self.catalog_repo = catalog_repo
        self.provisioning = provisioning

    async def list_all(self) -> list[VoiceProject]:
        return await self.project_repo.list_all()

    async def get(self, project_id: str) -> VoiceProject:
        project = await self.project_repo.get_by_id(project_id)
        if project is None:
            raise NotFoundError("Voice project not found.")
        return project

    async def assign_organization(self, project_id: str, organization_id: str) -> VoiceProject:
        project = await self.get(project_id)
        project.organization_id = organization_id
        return project

    async def assign_engineer(self, project_id: str, engineer_user_id: str) -> VoiceProject:
        project = await self.get(project_id)
        project.assigned_engineer_user_id = engineer_user_id
        return project

    async def add_requirement(self, project_id: str, key: str, value: str) -> Requirement:
        await self.get(project_id)  # 404s if missing
        return await self.project_repo.add_requirement(
            Requirement(voice_project_id=project_id, key=key, value=value)
        )

    async def list_requirements(self, project_id: str) -> list[Requirement]:
        return await self.project_repo.list_requirements(project_id)

    # VoiceProject phases map onto the generic ProvisionStatus lifecycle at
    # these two checkpoints — DEPLOYMENT_PENDING is where AIVRA commits to
    # deploying (mirrors PENDING_ACTIVATION), ACTIVE is where the customer
    # actually gains access (mirrors ACTIVE). Earlier phases (discovery,
    # configuration, testing, ...) are pre-entitlement engineering work and
    # have no ProvisionStatus equivalent.
    _PROVISION_CHECKPOINTS = {
        VoiceProjectStatus.DEPLOYMENT_PENDING: ProvisionStatus.PENDING_ACTIVATION,
        VoiceProjectStatus.ACTIVE: ProvisionStatus.ACTIVE,
        VoiceProjectStatus.DEPLOYMENT_FAILED: ProvisionStatus.DEPLOYMENT_FAILED,
    }

    async def transition(
        self,
        project_id: str,
        target_status: VoiceProjectStatus,
        *,
        failure_reason: str | None = None,
    ) -> VoiceProject:
        project = await self.get(project_id)
        VOICE_PROJECT_TRANSITIONS.assert_transition_allowed(project.status, target_status)
        project.status = target_status
        project.failure_reason = failure_reason if "FAILED" in target_status.name else None

        provision_status = self._PROVISION_CHECKPOINTS.get(target_status)
        if provision_status is not None:
            await self._mirror_provision(project, provision_status)
        return project

    async def _mirror_provision(self, project: VoiceProject, status: ProvisionStatus) -> None:
        if project.organization_id is None:
            raise ConflictError(
                "Voice project must be assigned to an organization before deployment."
            )
        voice_type = await self.catalog_repo.get_employee_type_by_code("voice")
        if voice_type is None:
            raise NotFoundError("Voice employee type is not configured in the catalog.")

        await self.provisioning.transition(
            organization_id=project.organization_id,
            employee_type_id=voice_type.id,
            target_status=status,
            reason=f"Voice project {project.id} reached {project.status.value}",
            actor_id=None,
            actor_type="SYSTEM",
            voice_project_id=project.id,
        )
