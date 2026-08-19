"""Double-submit CSRF protection for the cookie-carried refresh token.

The access token travels in the Authorization header (immune to CSRF), but
the refresh token is an httpOnly cookie so JS can't be tricked into leaking
it — which means the browser attaches it automatically on cross-site
requests too. We pair it with a non-httpOnly CSRF cookie whose value the
client must echo back in a header; a cross-site form post can't read the
cookie to do that.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings
from app.shared.errors.exceptions import ForbiddenError

CSRF_HEADER_NAME = "X-CSRF-Token"


def verify_csrf(request: Request) -> None:
    settings = get_settings()
    cookie_value = request.cookies.get(settings.csrf_cookie_name)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_value or not header_value or cookie_value != header_value:
        raise ForbiddenError("CSRF validation failed.")
