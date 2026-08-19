"""Composes catalog metadata with an organization's provisioning status
into the employee views the frontend consumes (``GET /employees``).
"""

from __future__ import annotations

from app.ai_employees.provisioning.models.provision import EmployeeProvision, ProvisionStatus
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.models.catalog import AIEmployeeType, EmployeeCatalogItem
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.ai_employees.registry.schemas.employee import EmployeeResponse
from app.shared.errors.exceptions import NotFoundError


def _to_response(
    employee_type: AIEmployeeType,
    catalog_item: EmployeeCatalogItem | None,
    provision: EmployeeProvision | None,
) -> EmployeeResponse:
    return EmployeeResponse(
        id=employee_type.id,
        type=employee_type.code,
        name=catalog_item.name if catalog_item else employee_type.name,
        description=(
            catalog_item.description if catalog_item else employee_type.description
        ),
        status=provision.status if provision else ProvisionStatus.NOT_PROVISIONED,
        commercial_model=employee_type.commercial_model,
        base_price_monthly=(
            float(catalog_item.base_price_monthly)
            if catalog_item and catalog_item.base_price_monthly is not None
            else None
        ),
        currency=catalog_item.currency if catalog_item else "USD",
    )


class EmployeeRegistryService:
    def __init__(self, catalog_repo: CatalogRepository, provisioning: ProvisioningService) -> None:
        self.catalog_repo = catalog_repo
        self.provisioning = provisioning

    async def list_employees_for_organization(self, organization_id: str) -> list[EmployeeResponse]:
        employee_types = await self.catalog_repo.list_employee_types()
        provisions = {
            p.employee_type_id: p
            for p in await self.provisioning.list_for_organization(organization_id)
        }

        responses: list[EmployeeResponse] = []
        for employee_type in employee_types:
            catalog_item = await self.catalog_repo.get_catalog_item_for_type(employee_type.id)
            provision = provisions.get(employee_type.id)
            responses.append(_to_response(employee_type, catalog_item, provision))
        return responses

    async def get_employee(self, organization_id: str, employee_type_id: str) -> EmployeeResponse:
        employee_type = await self.catalog_repo.get_employee_type(employee_type_id)
        if employee_type is None:
            raise NotFoundError("AI Employee type not found.")
        catalog_item = await self.catalog_repo.get_catalog_item_for_type(employee_type.id)
        provision = await self.provisioning.get_or_create_not_provisioned(
            organization_id=organization_id, employee_type_id=employee_type.id
        )
        return _to_response(employee_type, catalog_item, provision)
