"""Provisioning state transitions — the backend is the sole source of truth
for entitlement (spec section 1.1). Every transition is validated against
``PROVISION_TRANSITIONS`` and recorded as an immutable ``ProvisioningEvent``.

Callers: HR subscription activation calls ``activate`` when a subscription
becomes ACTIVE; Voice deployment calls ``activate`` only when AIVRA marks a
VoiceProject ACTIVE (spec section 8: "A Voice lead never automatically
creates an active subscription"). Neither HR nor Voice service code lives
here — this module only understands the generic provision lifecycle, kept
in the shared platform per the dependency rule (spec section 3.1).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.provisioning.models.provision import (
    PROVISION_TRANSITIONS,
    EmployeeProvision,
    ProvisioningEvent,
    ProvisionStatus,
)
from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.shared.errors.exceptions import EmployeeAccessDeniedError


class ProvisioningService:
    def __init__(self, repo: ProvisionRepository) -> None:
        self.repo = repo

    async def get_or_create_not_provisioned(
        self, *, organization_id: str, employee_type_id: str
    ) -> EmployeeProvision:
        existing = await self.repo.get_for_employee_type(organization_id, employee_type_id)
        if existing is not None:
            return existing
        provision = EmployeeProvision(
            organization_id=organization_id,
            employee_type_id=employee_type_id,
            status=ProvisionStatus.NOT_PROVISIONED,
        )
        return await self.repo.add(provision)

    async def list_for_organization(self, organization_id: str) -> list[EmployeeProvision]:
        return await self.repo.list_for_organization(organization_id)

    async def transition(
        self,
        *,
        organization_id: str,
        employee_type_id: str,
        target_status: ProvisionStatus,
        reason: str | None,
        actor_id: str | None,
        actor_type: str,
        subscription_id: str | None = None,
        voice_project_id: str | None = None,
    ) -> EmployeeProvision:
        provision = await self.get_or_create_not_provisioned(
            organization_id=organization_id, employee_type_id=employee_type_id
        )

        if provision.status == target_status:
            # Idempotent no-op — safe to call repeatedly from webhook retries
            # (spec section 28: idempotency for provisioning).
            return provision

        PROVISION_TRANSITIONS.assert_transition_allowed(provision.status, target_status)

        from_status = provision.status
        provision.status = target_status
        now = datetime.now(UTC)
        if target_status == ProvisionStatus.ACTIVE:
            provision.activated_at = now
        elif target_status == ProvisionStatus.PAUSED:
            provision.paused_at = now
        elif target_status == ProvisionStatus.CANCELLED:
            provision.cancelled_at = now

        if subscription_id is not None:
            provision.subscription_id = subscription_id
        if voice_project_id is not None:
            provision.voice_project_id = voice_project_id

        await self.repo.add_event(
            ProvisioningEvent(
                organization_id=organization_id,
                employee_provision_id=provision.id,
                from_status=from_status,
                to_status=target_status,
                reason=reason,
                actor_id=actor_id,
                actor_type=actor_type,
            )
        )
        return provision

    async def require_active(
        self, organization_id: str, employee_type_id: str
    ) -> EmployeeProvision:
        provision = await self.repo.get_for_employee_type(organization_id, employee_type_id)
        if provision is None or provision.status != ProvisionStatus.ACTIVE:
            raise EmployeeAccessDeniedError(
                "The requested AI Employee is not active for this organization."
            )
        return provision
