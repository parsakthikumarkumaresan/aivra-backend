"""JWT access tokens and opaque refresh tokens.

Access tokens are short-lived, stateless JWTs carrying identity + the active
organization/role claims needed for authorization without a DB round trip.
Refresh tokens are opaque random strings; only their Argon2 hash is
persisted (``identity.models.RefreshToken``), so a leaked DB dump does not
yield usable tokens. See ``app.identity.services.auth_service`` for
rotation/reuse-detection logic.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings
from app.shared.errors.exceptions import TokenExpiredError, TokenInvalidError


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: str
    organization_id: str | None
    role: str | None
    session_id: str


def create_access_token(
    *, user_id: str, organization_id: str | None, role: str | None, session_id: str
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "org_id": organization_id,
        "role": role,
        "sid": session_id,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        "type": "access",
    }
    return jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> AccessTokenClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "sid"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("Access token is invalid.") from exc

    if payload.get("type") != "access":
        raise TokenInvalidError("Token is not an access token.")

    return AccessTokenClaims(
        user_id=payload["sub"],
        organization_id=payload.get("org_id"),
        role=payload.get("role"),
        session_id=payload["sid"],
    )


def generate_opaque_token() -> str:
    """Raw secret handed to the client (cookie/body) — never stored as-is."""
    return secrets.token_urlsafe(48)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
