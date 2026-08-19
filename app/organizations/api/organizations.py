from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.repositories.user_repository import UserRepository
from app.organizations.repositories.membership_repository import MembershipRepository
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.organizations.schemas.organization import (
    CreateOrganizationRequest,
    InviteMemberRequest,
    OrganizationMemberResponse,
    OrganizationResponse,
    UpdateOrganizationRequest,
)
from app.organizations.services.organization_service import OrganizationService
from app.shared.database.session import get_db
from app.shared.rbac.roles import ORG_MANAGEMENT_ROLES, OrgRole
from app.shared.security.dependencies import (
    AuthContext,
    get_auth_context,
    require_organization_context,
    require_role,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _service(db: AsyncSession = Depends(get_db)) -> OrganizationService:
    return OrganizationService(
        OrganizationRepository(db), MembershipRepository(db), UserRepository(db)
    )


def _user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    payload: CreateOrganizationRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: OrganizationService = Depends(_service),
) -> OrganizationResponse:
    organization = await service.create_organization(
        owner_user_id=auth.user.id,
        name=payload.name,
        slug=payload.slug,
        industry=payload.industry,
        timezone=payload.timezone,
    )
    return OrganizationResponse.model_validate(organization)


@router.get("/me", response_model=OrganizationResponse)
async def get_current_organization(
    auth: AuthContext = Depends(require_organization_context),
    service: OrganizationService = Depends(_service),
) -> OrganizationResponse:
    organization = await service.get_organization(auth.require_organization_id())
    return OrganizationResponse.model_validate(organization)


@router.patch("/me", response_model=OrganizationResponse)
async def update_current_organization(
    payload: UpdateOrganizationRequest,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: OrganizationService = Depends(_service),
) -> OrganizationResponse:
    organization = await service.update_organization(
        organization_id=auth.require_organization_id(),
        name=payload.name,
        industry=payload.industry,
        timezone=payload.timezone,
    )
    return OrganizationResponse.model_validate(organization)


@router.get("/me/members", response_model=list[OrganizationMemberResponse])
async def list_members(
    auth: AuthContext = Depends(require_role(*OrgRole)),
    service: OrganizationService = Depends(_service),
    user_repo: UserRepository = Depends(_user_repo),
) -> list[OrganizationMemberResponse]:
    members = await service.list_members(auth.require_organization_id())
    responses: list[OrganizationMemberResponse] = []
    for member in members:
        user = await user_repo.get_by_id(member.user_id)
        if user is None:
            continue
        responses.append(
            OrganizationMemberResponse(
                id=member.id,
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=member.role,
                status=member.status,
            )
        )
    return responses


@router.post("/me/members", response_model=OrganizationMemberResponse, status_code=201)
async def invite_member(
    payload: InviteMemberRequest,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: OrganizationService = Depends(_service),
    user_repo: UserRepository = Depends(_user_repo),
) -> OrganizationMemberResponse:
    member = await service.invite_member(
        organization_id=auth.require_organization_id(),
        inviter_user_id=auth.user.id,
        email=payload.email,
        role=OrgRole(payload.role),
    )
    invitee = await user_repo.get_by_id(member.user_id)
    assert invitee is not None  # service just validated this user exists
    return OrganizationMemberResponse(
        id=member.id,
        user_id=invitee.id,
        email=invitee.email,
        full_name=invitee.full_name,
        role=member.role,
        status=member.status,
    )
