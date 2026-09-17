from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends

from app.ai_employees.provisioning.dependencies import require_employee_active
from app.ai_employees.registry.models.catalog import EmployeeTypeCode
from app.shared.rbac.roles import ORG_MANAGEMENT_ROLES, OrgRole
from app.shared.security.dependencies import (
    AuthContext,
    require_role,
)

require_voice_active = require_employee_active(EmployeeTypeCode.VOICE)


def require_voice_role(*allowed_roles: OrgRole) -> Callable[..., Awaitable[AuthContext]]:
    """Combined auth dependency for customer-facing Voice routes:
    active Voice entitlement + allowed OrgRole.
    """

    async def _dependency(
        auth: AuthContext = Depends(require_role(*allowed_roles)),
        _entitlement: AuthContext = Depends(require_voice_active),
    ) -> AuthContext:
        return auth

    return _dependency


def require_voice_internal_role() -> Callable[..., Awaitable[AuthContext]]:
    """Combined auth dependency for the Voice Agent Builder routes
    (GET/POST /internal/voice-agents/...).

    Grants access to org owners and admins who have an active Voice
    entitlement — matching the same pattern as HR's builder routes
    (require_hr_role(*HR_OPERATOR_ROLES)). Platform roles (aivra_admin/
    aivra_engineer) are NOT required here; these are customer-facing
    builder routes, not AIVRA-internal engineering routes.
    """

    async def _dependency(
        auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
        _entitlement: AuthContext = Depends(require_voice_active),
    ) -> AuthContext:
        return auth

    return _dependency

