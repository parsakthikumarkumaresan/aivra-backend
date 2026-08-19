"""RQ queue client. RQ uses synchronous redis-py (not redis.asyncio) — kept
separate from app.shared.cache.redis_client, which is the async client used
by request-path code (rate limiting).
"""

from __future__ import annotations

import redis
from rq import Queue

from app.core.config import get_settings

_queue: Queue | None = None


def get_queue() -> Queue:
    global _queue
    if _queue is None:
        connection = redis.Redis.from_url(get_settings().redis_url)
        _queue = Queue("hr", connection=connection)
    return _queue
