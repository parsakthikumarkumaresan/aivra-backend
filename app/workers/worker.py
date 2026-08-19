"""Background worker process entrypoint.

Run with: ``python -m app.workers.worker``

Deliberately a separate process from the API (spec section 31: workers are
independent of the FastAPI process) so AI/document processing never
competes with request-handling for the same event loop or connection pool.
"""

from __future__ import annotations

import sys

import redis
from rq import SimpleWorker, Worker

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

# The worker process only ever directly imports the specific models each
# job module touches, so SQLAlchemy's declarative metadata is otherwise
# incomplete in this process — a flush on any model with a cross-context FK
# (e.g. Assessment.organization_id -> organizations.id) then fails with
# NoReferencedTableError because `Organization` was never registered.
# Importing the full model registry here (the one place allowed to see
# every bounded context, see all_models.py's own docstring) guarantees
# every job function gets complete metadata regardless of which one runs.
from app.shared.database.all_models import Base  # noqa: F401,E402

configure_logging()
logger = get_logger(__name__)


QUEUES = ["hr", "knowledge", "voice"]


def main() -> None:
    settings = get_settings()
    connection = redis.Redis.from_url(settings.redis_url)
    # RQ's default Worker forks a subprocess per job (os.fork), which does
    # not exist on Windows — every job crashes the worker immediately with
    # AttributeError before doing any work. SimpleWorker runs jobs in the
    # same process instead (no fork), which is required on win32 and is
    # RQ's own documented workaround for platforms without fork support.
    worker_class = SimpleWorker if sys.platform == "win32" else Worker
    worker = worker_class(QUEUES, connection=connection)
    logger.info("worker_starting", queues=QUEUES, worker_class=worker_class.__name__)
    worker.work()


if __name__ == "__main__":
    main()
