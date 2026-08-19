from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.ai_employees.registry.schemas.employee import EmployeeAccessResponse, EmployeeResponse
from app.ai_employees.registry.services.employee_registry_service import EmployeeRegistryService
from app.shared.database.session import get_db
from app.shared.security.dependencies import AuthContext, require_organization_context

router = APIRouter(prefix="/employees", tags=["employees"])


def _service(db: AsyncSession = Depends(get_db)) -> EmployeeRegistryService:
    return EmployeeRegistryService(
        CatalogRepository(db), ProvisioningService(ProvisionRepository(db))
    )


@router.get("", response_model=list[EmployeeResponse])
async def list_employees(
    auth: AuthContext = Depends(require_organization_context),
    service: EmployeeRegistryService = Depends(_service),
) -> list[EmployeeResponse]:
    return await service.list_employees_for_organization(auth.require_organization_id())


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: str,
    auth: AuthContext = Depends(require_organization_context),
    service: EmployeeRegistryService = Depends(_service),
) -> EmployeeResponse:
    return await service.get_employee(auth.require_organization_id(), employee_id)


@router.get("/{employee_id}/access", response_model=EmployeeAccessResponse)
async def get_employee_access(
    employee_id: str,
    auth: AuthContext = Depends(require_organization_context),
    service: EmployeeRegistryService = Depends(_service),
) -> EmployeeAccessResponse:
    employee = await service.get_employee(auth.require_organization_id(), employee_id)
    return EmployeeAccessResponse(
        employee_type=employee.type, status=employee.status, is_active=employee.status == "active"
    )
