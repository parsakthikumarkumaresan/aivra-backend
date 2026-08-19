from __future__ import annotations

from app.audit.models.audit_event import ActorType, AuditEvent, AuditResult
from app.audit.repositories.audit_repository import AuditRepository
from app.core.logging import request_id_ctx


class AuditService:
    def __init__(self, repo: AuditRepository) -> None:
        self.repo = repo

    async def record(
        self,
        *,
        organization_id: str,
        actor_id: str | None,
        actor_type: ActorType,
        action: str,
        resource_type: str,
        resource_id: str,
        result: AuditResult = AuditResult.SUCCESS,
    ) -> AuditEvent:
        event = AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            request_id=request_id_ctx.get(),
        )
        return await self.repo.add(event)
