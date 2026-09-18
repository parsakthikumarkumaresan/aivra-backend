"""JEXA Admin — Customer Directory + Customer Detail (Phase 5).

AIVRA-internal only (require_platform_role) — never reachable by a
customer session, regardless of their OrgRole. Reuses the existing
Organization/EmployeeProvision/VoiceProject/OrganizationMember models and
repositories; no new tables, no second credit ledger (Jaan Voice Credits
stay owned by app.ai_employees.voice — see admin_credits_routes.py).
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.models.provision import EmployeeProvision
from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.ai_employees.registry.models.catalog import AIEmployeeType
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.identity.repositories.user_repository import UserRepository
from app.leads.repositories.voice_project_repository import VoiceProjectRepository
from app.organizations.models.organization import Organization
from app.organizations.repositories.membership_repository import MembershipRepository
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.organizations.schemas.organization import (
    AdminEmployeeProvisionSummary,
    AdminOrganizationDetailResponse,
    AdminOrganizationListResponse,
    AdminOrganizationSummaryResponse,
    AdminVoiceProjectSummary,
    OrganizationMemberResponse,
)
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import PlatformRole
from app.shared.security.dependencies import require_platform_role

router = APIRouter(
    prefix="/internal/organizations",
    tags=["Admin — Customers"],
    dependencies=[
        Depends(require_platform_role(PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER))
    ],
)


async def _employee_type_map(catalog_repo: CatalogRepository) -> dict[str, AIEmployeeType]:
    types = await catalog_repo.list_employee_types()
    return {t.id: t for t in types}


def _to_provision_summary(
    provision: EmployeeProvision, type_map: dict[str, AIEmployeeType]
) -> AdminEmployeeProvisionSummary:
    employee_type = type_map.get(provision.employee_type_id)
    return AdminEmployeeProvisionSummary(
        employee_type_code=employee_type.code.value if employee_type else "unknown",
        employee_type_name=employee_type.name if employee_type else "Unknown",
        status=provision.status.value,
        activated_at=provision.activated_at,
    )


@router.get("", response_model=AdminOrganizationListResponse)
async def list_organizations(
    search: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
) -> AdminOrganizationListResponse:
    org_repo = OrganizationRepository(db)
    provision_repo = ProvisionRepository(db)
    catalog_repo = CatalogRepository(db)

    organizations, total = await org_repo.search_and_count(
        query=search, page=page, page_size=page_size
    )
    org_ids = [org.id for org in organizations]

    provisions = await provision_repo.list_for_organizations(org_ids)
    provisions_by_org: dict[str, list[EmployeeProvision]] = defaultdict(list)
    for p in provisions:
        provisions_by_org[p.organization_id].append(p)

    type_map = await _employee_type_map(catalog_repo)

    items = [
        AdminOrganizationSummaryResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            industry=org.industry,
            status=org.status.value,
            created_at=org.created_at,
            employee_provisions=[
                _to_provision_summary(p, type_map) for p in provisions_by_org.get(org.id, [])
            ],
        )
        for org in organizations
    ]
    return AdminOrganizationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{organization_id}", response_model=AdminOrganizationDetailResponse)
async def get_organization_detail(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> AdminOrganizationDetailResponse:
    org_repo = OrganizationRepository(db)
    provision_repo = ProvisionRepository(db)
    catalog_repo = CatalogRepository(db)
    voice_project_repo = VoiceProjectRepository(db)
    membership_repo = MembershipRepository(db)
    user_repo = UserRepository(db)

    organization: Organization | None = await org_repo.get_by_id(organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")

    type_map = await _employee_type_map(catalog_repo)
    provisions = await provision_repo.list_for_organization(organization_id)
    voice_projects = await voice_project_repo.list_for_organization(organization_id)
    memberships = await membership_repo.list_members(organization_id)

    members: list[OrganizationMemberResponse] = []
    for member in memberships:
        user = await user_repo.get_by_id(member.user_id)
        if user is None:
            continue
        members.append(
            OrganizationMemberResponse(
                id=member.id,
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=member.role.value,
                status=member.status.value,
            )
        )

    return AdminOrganizationDetailResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        industry=organization.industry,
        timezone=organization.timezone,
        status=organization.status.value,
        created_at=organization.created_at,
        employee_provisions=[_to_provision_summary(p, type_map) for p in provisions],
        voice_projects=[
            AdminVoiceProjectSummary(id=vp.id, name=vp.name, status=vp.status.value)
            for vp in voice_projects
        ],
        members=members,
    )
