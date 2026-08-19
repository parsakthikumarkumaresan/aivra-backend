from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.repositories.session_repository import SessionRepository
from app.identity.repositories.user_repository import UserRepository
from app.identity.services.auth_service import AuthService
from app.organizations.repositories.membership_repository import MembershipRepository
from app.shared.errors.exceptions import TokenInvalidError


def _service(db_session: AsyncSession) -> AuthService:
    return AuthService(
        UserRepository(db_session), SessionRepository(db_session), MembershipRepository(db_session)
    )


async def test_refresh_token_reuse_revokes_entire_session_family(db_session: AsyncSession) -> None:
    service = _service(db_session)
    await service.register(email="reuse@example.com", password="SuperSecret123!", full_name="X")
    login_result = await service.login(
        email="reuse@example.com", password="SuperSecret123!", user_agent=None, ip_address=None
    )
    original_refresh_token = login_result.refresh_token

    # First use rotates it — legitimate.
    rotated = await service.refresh(raw_refresh_token=original_refresh_token)
    assert rotated.refresh_token != original_refresh_token

    # Reusing the now-rotated-out original token is theft evidence: rejected...
    with pytest.raises(TokenInvalidError):
        await service.refresh(raw_refresh_token=original_refresh_token)

    # ...and the legitimate, newly-rotated token is now also dead (whole family revoked).
    with pytest.raises(TokenInvalidError):
        await service.refresh(raw_refresh_token=rotated.refresh_token)


async def test_expired_refresh_token_is_rejected(db_session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    service = _service(db_session)
    await service.register(email="expired@example.com", password="SuperSecret123!", full_name="X")
    login_result = await service.login(
        email="expired@example.com", password="SuperSecret123!", user_agent=None, ip_address=None
    )

    token_row = await SessionRepository(db_session).get_refresh_token_by_raw(
        login_result.refresh_token
    )
    assert token_row is not None
    token_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    from app.shared.errors.exceptions import TokenExpiredError

    with pytest.raises(TokenExpiredError):
        await service.refresh(raw_refresh_token=login_result.refresh_token)
