"""Login, session/refresh-token rotation, logout and organization selection.

Refresh tokens rotate on every use. Presenting an already-revoked refresh
token is treated as theft evidence and revokes the entire session family
(spec section 23: session security).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.identity.models.session import RefreshToken, Session
from app.identity.models.user import User
from app.identity.repositories.session_repository import SessionRepository
from app.identity.repositories.user_repository import UserRepository
from app.organizations.repositories.membership_repository import MembershipRepository
from app.shared.errors.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.shared.rbac.roles import OrgRole
from app.shared.security.hashing import hash_token
from app.shared.security.passwords import hash_password, verify_password
from app.shared.security.tokens import create_access_token, generate_opaque_token


@dataclass(frozen=True)
class AuthResult:
    user: User
    session_id: str
    access_token: str
    refresh_token: str
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    organization_id: str | None
    role: str | None


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.membership_repo = membership_repo
        self.settings = get_settings()

    async def register(self, *, email: str, password: str, full_name: str) -> User:
        existing = await self.user_repo.get_by_email(email)
        if existing is not None:
            raise InvalidCredentialsError("An account with this email already exists.")
        user = User(
            email=email.lower().strip(), password_hash=hash_password(password), full_name=full_name
        )
        return await self.user_repo.add(user)

    async def login(
        self, *, email: str, password: str, user_agent: str | None, ip_address: str | None
    ) -> AuthResult:
        user = await self.user_repo.get_by_email(email)
        if user is None:
            raise InvalidCredentialsError("Invalid email or password.")

        now = datetime.now(UTC)
        if user.locked_until and user.locked_until > now:
            raise AccountLockedError("Account temporarily locked due to failed login attempts.")

        if not user.is_active or not verify_password(password, user.password_hash):
            if user.is_active:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= self.settings.login_max_attempts:
                    user.locked_until = now + timedelta(seconds=self.settings.login_lockout_seconds)
            raise InvalidCredentialsError("Invalid email or password.")

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now

        organization_id, role = await self._default_org_context(user)
        return await self._issue_session(
            user, organization_id, role, user_agent=user_agent, ip_address=ip_address
        )

    async def refresh(self, *, raw_refresh_token: str) -> AuthResult:
        token = await self.session_repo.get_refresh_token_by_raw(raw_refresh_token)
        if token is None:
            raise TokenInvalidError("Refresh token is invalid.")

        if token.revoked_at is not None:
            # Reuse of an already-rotated token — likely theft. Kill the whole family.
            await self.session_repo.revoke_session_family(token.session_id)
            raise TokenInvalidError("Refresh token has already been used.")

        now = datetime.now(UTC)
        if token.expires_at < now:
            raise TokenExpiredError("Refresh token has expired.")

        user = await self.user_repo.get_by_id(token.user_id)
        if user is None or not user.is_active:
            raise TokenInvalidError("Account is no longer active.")

        session_row = await self.session_repo.get_session(token.session_id)
        if session_row is None or session_row.revoked_at is not None:
            raise TokenInvalidError("Session has been revoked.")

        organization_id = session_row.organization_id
        role = await self._role_for_org(user, organization_id) if organization_id else None

        new_token, raw_new_token = await self._issue_refresh_token(user, session_row)
        token.revoked_at = now
        token.replaced_by_id = new_token.id
        session_row.last_seen_at = now

        access_token = create_access_token(
            user_id=user.id,
            organization_id=organization_id,
            role=role.value if role else None,
            session_id=session_row.id,
        )
        return AuthResult(
            user=user,
            session_id=session_row.id,
            access_token=access_token,
            refresh_token=raw_new_token,
            access_token_ttl_seconds=self.settings.access_token_ttl_seconds,
            refresh_token_ttl_seconds=self.settings.refresh_token_ttl_seconds,
            organization_id=organization_id,
            role=role.value if role else None,
        )

    async def logout(self, *, session_id: str) -> None:
        await self.session_repo.revoke_session_family(session_id)

    async def select_organization(
        self, *, user: User, session_id: str, organization_id: str
    ) -> AuthResult:
        role = await self._role_for_org(user, organization_id)
        if role is None:
            raise InvalidCredentialsError("You are not a member of this organization.")

        session_row = await self.session_repo.get_session(session_id)
        if session_row is None or session_row.revoked_at is not None:
            raise TokenInvalidError("Session has been revoked.")
        session_row.organization_id = organization_id

        access_token = create_access_token(
            user_id=user.id, organization_id=organization_id, role=role.value, session_id=session_id
        )
        return AuthResult(
            user=user,
            session_id=session_id,
            access_token=access_token,
            refresh_token="",
            access_token_ttl_seconds=self.settings.access_token_ttl_seconds,
            refresh_token_ttl_seconds=0,
            organization_id=organization_id,
            role=role.value,
        )

    async def _default_org_context(
        self, user: User
    ) -> tuple[str | None, OrgRole | None]:
        if user.platform_role is not None:
            return None, None
        memberships = await self.membership_repo.list_memberships_for_user(user.id)
        if len(memberships) == 1:
            return memberships[0].organization_id, memberships[0].role
        return None, None

    async def _role_for_org(self, user: User, organization_id: str) -> OrgRole | None:
        membership = await self.membership_repo.get_active_membership(organization_id, user.id)
        return membership.role if membership else None

    async def _issue_session(
        self,
        user: User,
        organization_id: str | None,
        role: OrgRole | None,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuthResult:
        session_row = Session(
            user_id=user.id,
            organization_id=organization_id,
            user_agent=user_agent,
            ip_address=ip_address,
            last_seen_at=datetime.now(UTC),
        )
        session_row = await self.session_repo.add_session(session_row)
        _refresh_token, raw_token = await self._issue_refresh_token(user, session_row)

        access_token = create_access_token(
            user_id=user.id,
            organization_id=organization_id,
            role=role.value if role else None,
            session_id=session_row.id,
        )
        return AuthResult(
            user=user,
            session_id=session_row.id,
            access_token=access_token,
            refresh_token=raw_token,
            access_token_ttl_seconds=self.settings.access_token_ttl_seconds,
            refresh_token_ttl_seconds=self.settings.refresh_token_ttl_seconds,
            organization_id=organization_id,
            role=role.value if role else None,
        )

    async def _issue_refresh_token(
        self, user: User, session_row: Session
    ) -> tuple[RefreshToken, str]:
        raw_token = generate_opaque_token()
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.refresh_token_ttl_seconds)
        token = RefreshToken(
            session_id=session_row.id,
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
        token = await self.session_repo.add_refresh_token(token)
        return token, raw_token


__all__ = ["AuthService", "AuthResult"]
