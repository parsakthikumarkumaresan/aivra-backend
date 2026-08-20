from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.shared.schemas.base import CamelModel


class JobResponse(CamelModel):
    id: str
    title: str
    company_name: str | None
    ai_agent_name: str | None
    department: str | None
    description: str | None
    requirements: list[str]
    location: str | None
    employment_type: str
    status: str
    created_at: datetime
    # Not a column on HrJob — computed by JobService.list_jobs/get_job from a
    # real COUNT query, never left unset (frontend Job.candidateCount is
    # required, not optional).
    candidate_count: int = 0


class CreateJobRequest(CamelModel):
    title: str = Field(min_length=1, max_length=255)
    company_name: str | None = None
    ai_agent_name: str | None = None
    department: str | None = None
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    location: str | None = None
    employment_type: str = "full_time"
