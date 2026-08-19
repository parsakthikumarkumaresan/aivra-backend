from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends

from app.ai_employees.provisioning.dependencies import require_employee_active
from app.ai_employees.registry.models.catalog import EmployeeTypeCode
from app.shared.rbac.roles import INTERNAL_VOICE_ROLES, OrgRole
from app.shared.security.dependencies import (
    AuthContext,
    require_organization_context,
    require_platform_role,
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
    """Combined auth dependency for internal Voice Builder routes:
    active Voice entitlement + AIVRA PlatformRole.
    """

    async def _dependency(
        auth: AuthContext = Depends(require_platform_role(*INTERNAL_VOICE_ROLES)),
        _org_context: AuthContext = Depends(require_organization_context),
        _entitlement: AuthContext = Depends(require_voice_active),
    ) -> AuthContext:
        return auth

    return _dependency
