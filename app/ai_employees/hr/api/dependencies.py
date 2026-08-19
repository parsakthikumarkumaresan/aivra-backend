"""Combined auth dependency for HR routes: active HR entitlement + role.

Composing these as two separate ``Depends(...)`` params on every route is
easy to get wrong (forgetting the entitlement check is a real access-control
bug, not just a style nit) — this factory makes "HR must be ACTIVE for this
org AND the caller must hold an allowed role" a single dependency.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends

from app.ai_employees.provisioning.dependencies import require_employee_active
from app.ai_employees.registry.models.catalog import EmployeeTypeCode
from app.shared.rbac.roles import OrgRole
from app.shared.security.dependencies import AuthContext, require_role

require_hr_active = require_employee_active(EmployeeTypeCode.HR)


def require_hr_role(*allowed_roles: OrgRole) -> Callable[..., Awaitable[AuthContext]]:
    async def _dependency(
        auth: AuthContext = Depends(require_role(*allowed_roles)),
        _entitlement: AuthContext = Depends(require_hr_active),
    ) -> AuthContext:
        return auth

    return _dependency
