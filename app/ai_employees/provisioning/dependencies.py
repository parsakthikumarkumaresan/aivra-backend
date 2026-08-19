"""FastAPI dependency gating access to an AI Employee's routes by entitlement.

Used by HR and Voice (customer-safe) API routers — this lives in the shared
platform, not in HR or Voice domain code, so importing it from either
context does not violate the HR/Voice isolation rule (spec section 3.1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.models.catalog import EmployeeTypeCode
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.shared.database.session import get_db
from app.shared.errors.exceptions import EmployeeAccessDeniedError
from app.shared.security.dependencies import AuthContext, require_organization_context


def require_employee_active(
    employee_type_code: EmployeeTypeCode,
) -> Callable[..., Awaitable[AuthContext]]:
    async def _dependency(
        auth: AuthContext = Depends(require_organization_context),
        db: AsyncSession = Depends(get_db),
    ) -> AuthContext:
        employee_type = await CatalogRepository(db).get_employee_type_by_code(employee_type_code)
        if employee_type is None:
            raise EmployeeAccessDeniedError("This AI Employee is not available.")
        await ProvisioningService(ProvisionRepository(db)).require_active(
            auth.require_organization_id(), employee_type.id
        )
        return auth

    return _dependency
