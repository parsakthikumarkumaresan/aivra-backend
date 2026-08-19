from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class ProcessingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProcessingJob(Base, OrgScopedMixin):
    """Execution record for one async ``resume.process`` run (spec section
    22). One Resume can have multiple ProcessingJob rows across retries —
    this is the audit trail, not the resume's own status (see
    ``Resume.status`` for current pipeline stage).
    """

    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.PROCESSING_JOB)
    )
    resume_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(60), default="resume_pipeline", nullable=False)
    status: Mapped[ProcessingJobStatus] = mapped_column(
        str_enum_column(ProcessingJobStatus, 20), default=ProcessingJobStatus.QUEUED, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
