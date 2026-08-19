"""Background worker process entrypoint.

Run with: ``python -m app.workers.worker``

Deliberately a separate process from the API (spec section 31: workers are
independent of the FastAPI process) so AI/document processing never
competes with request-handling for the same event loop or connection pool.
"""

from __future__ import annotations

import redis
from rq import Worker

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


QUEUES = ["hr", "knowledge", "voice"]


def main() -> None:
    settings = get_settings()
    connection = redis.Redis.from_url(settings.redis_url)
    worker = Worker(QUEUES, connection=connection)
    logger.info("worker_starting", queues=QUEUES)
    worker.work()


if __name__ == "__main__":
    main()
