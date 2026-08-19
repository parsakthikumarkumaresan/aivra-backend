from __future__ import annotations

from app.ai_employees.hr.models.processing_job import ProcessingJob
from app.shared.database.repository import OrgScopedRepository


class ProcessingJobRepository(OrgScopedRepository[ProcessingJob]):
    model = ProcessingJob
