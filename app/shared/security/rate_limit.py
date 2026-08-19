"""Redis-backed fixed-window rate limiting (spec sections 6, 23, 29).

Applied per-request via a FastAPI dependency so each protected route
declares its own limit explicitly rather than relying on a single global
policy. Uses Redis INCR + EXPIRE (only the first request in a window sets
the TTL), which is a standard, simple fixed-window approach — adequate for
abuse protection on public/auth endpoints without adding a sliding-window
or token-bucket library.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request

from app.shared.cache.redis_client import get_redis
from app.shared.errors.exceptions import RateLimitedError


def rate_limit(
    *, key_prefix: str, max_requests: int, window_seconds: int
) -> Callable[[Request], Awaitable[None]]:
    """Returns a dependency callable — use as ``Depends(rate_limit(...))``,
    matching the ``require_role(...)`` factory pattern elsewhere.
    """

    async def _dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        redis = get_redis()
        key = f"ratelimit:{key_prefix}:{client_ip}"

        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window_seconds)

        if current > max_requests:
            raise RateLimitedError(
                "Too many requests. Try again in a few minutes.",
                details={"limit": max_requests, "window_seconds": window_seconds},
            )

    return _dependency
