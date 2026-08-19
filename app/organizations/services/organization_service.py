"""Organization lifecycle and membership management.

Invites currently require the invitee to already have an AIVRA account
(registered via /auth/register). Email-based invites for not-yet-registered
users are a real, separate feature (pending-invite token + registration
completion) that is out of MVP scope — see spec section 41 MVP discipline —
and is not faked here; ``NotFoundError`` is raised explicitly instead.
"""

from __future__ import annotations

from app.identity.repositories.user_repository import UserRepository
from app.organizations.models.membership import MembershipStatus, OrganizationMember
from app.organizations.models.organization import Organization
from app.organizations.repositories.membership_repository import MembershipRepository
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.shared.errors.exceptions import ConflictError, NotFoundError
from app.shared.rbac.roles import OrgRole


class OrganizationService:
    def __init__(
        self,
        org_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
    ) -> None:
        self.org_repo = org_repo
        self.membership_repo = membership_repo
        self.user_repo = user_repo

    async def create_organization(
        self, *, owner_user_id: str, name: str, slug: str, industry: str | None, timezone: str
    ) -> Organization:
        existing = await self.org_repo.get_by_slug(slug)
        if existing is not None:
            raise ConflictError(f"Organization slug '{slug}' is already taken.")

        organization = await self.org_repo.add(
            Organization(name=name, slug=slug, industry=industry, timezone=timezone)
        )
        await self.membership_repo.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=owner_user_id,
                role=OrgRole.OWNER,
                status=MembershipStatus.ACTIVE,
            )
        )
        return organization

    async def get_organization(self, organization_id: str) -> Organization:
        organization = await self.org_repo.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError("Organization not found.")
        return organization

    async def update_organization(
        self,
        *,
        organization_id: str,
        name: str | None,
        industry: str | None,
        timezone: str | None,
    ) -> Organization:
        organization = await self.get_organization(organization_id)
        if name is not None:
            organization.name = name
        if industry is not None:
            organization.industry = industry
        if timezone is not None:
            organization.timezone = timezone
        return organization

    async def list_members(self, organization_id: str) -> list[OrganizationMember]:
        return await self.membership_repo.list_members(organization_id)

    async def invite_member(
        self, *, organization_id: str, inviter_user_id: str, email: str, role: OrgRole
    ) -> OrganizationMember:
        invitee = await self.user_repo.get_by_email(email)
        if invitee is None:
            raise NotFoundError(
                "No AIVRA account exists for this email yet. Ask them to register first."
            )
        existing = await self.membership_repo.get_active_membership(organization_id, invitee.id)
        if existing is not None:
            raise ConflictError("This user is already a member of the organization.")

        return await self.membership_repo.add(
            OrganizationMember(
                organization_id=organization_id,
                user_id=invitee.id,
                role=role,
                status=MembershipStatus.ACTIVE,
                invited_by_user_id=inviter_user_id,
            )
        )
