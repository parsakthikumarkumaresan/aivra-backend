from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.shared.schemas.base import CamelModel


class JobResponse(CamelModel):
    id: str
    title: str
    department: str | None
    description: str | None
    requirements: list[str]
    location: str | None
    employment_type: str
    status: str
    created_at: datetime


class CreateJobRequest(CamelModel):
    title: str = Field(min_length=1, max_length=255)
    department: str | None = None
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    location: str | None = None
    employment_type: str = "full_time"
