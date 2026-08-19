"""FastAPI auth dependencies.

Every protected route composes these rather than re-implementing checks:
authentication -> active organization membership -> role permission ->
(for employee-scoped routes) entitlement. Frontend route guards are not
authorization (spec section 6) — these dependencies are the real boundary.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import actor_id_ctx, organization_id_ctx
from app.identity.models.user import User
from app.identity.repositories.user_repository import UserRepository
from app.organizations.repositories.membership_repository import MembershipRepository
from app.shared.database.session import get_db
from app.shared.errors.exceptions import (
    AuthenticationRequiredError,
    ForbiddenError,
    MembershipRequiredError,
    RoleNotPermittedError,
    TokenInvalidError,
)
from app.shared.rbac.roles import OrgRole, PlatformRole
from app.shared.security.tokens import AccessTokenClaims, decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Authenticated identity resolved for the current request."""

    user: User
    claims: AccessTokenClaims

    @property
    def organization_id(self) -> str | None:
        return self.claims.organization_id

    def require_organization_id(self) -> str:
        """For call sites reached only via ``require_organization_context``
        (or ``require_role``/employee-entitlement dependencies built on it),
        where organization_id is already guaranteed non-None — avoids
        scattering ``# type: ignore[arg-type]`` at every such call site.
        """
        if self.claims.organization_id is None:
            raise MembershipRequiredError("An active organization must be selected.")
        return self.claims.organization_id

    @property
    def role(self) -> OrgRole | None:
        return OrgRole(self.claims.role) if self.claims.role else None

    @property
    def platform_role(self) -> PlatformRole | None:
        return self.user.platform_role


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if credentials is None:
        raise AuthenticationRequiredError("Authentication is required.")

    claims = decode_access_token(credentials.credentials)
    user = await UserRepository(db).get_by_id(claims.user_id)
    if user is None or not user.is_active:
        raise TokenInvalidError("Account is no longer active.")

    actor_id_ctx.set(user.id)
    if claims.organization_id:
        organization_id_ctx.set(claims.organization_id)
    return AuthContext(user=user, claims=claims)


async def require_organization_context(
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Guarantee the caller has an active organization selected AND a live
    membership row backing it — the JWT claim alone is not re-verified
    against the DB on every request for staleness reasons, so we check here
    for endpoints where membership state (e.g. removal) must be current.
    """
    if auth.organization_id is None:
        raise MembershipRequiredError("An active organization must be selected.")

    membership = await MembershipRepository(db).get_active_membership(
        auth.organization_id, auth.user.id
    )
    if membership is None:
        raise MembershipRequiredError("You are not an active member of this organization.")

    return auth


def require_role(*allowed_roles: OrgRole) -> Callable[..., Awaitable[AuthContext]]:
    async def _dependency(
        auth: AuthContext = Depends(require_organization_context),
    ) -> AuthContext:
        if auth.role not in allowed_roles:
            raise RoleNotPermittedError("Your role does not permit this action.")
        return auth

    return _dependency


def require_platform_role(*allowed_roles: PlatformRole) -> Callable[..., Awaitable[AuthContext]]:
    async def _dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth.platform_role not in allowed_roles:
            raise ForbiddenError("This action requires AIVRA internal access.")
        return auth

    return _dependency
