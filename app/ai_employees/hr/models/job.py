from __future__ import annotations

from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class JobStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"


class HrJob(Base, OrgScopedMixin):
    __tablename__ = "hr_jobs"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.HR_JOB)
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    # Per-job override for the AI screening agent's spoken display name
    # (e.g. "Zara") — falls back to settings.hr_screening_persona_name when
    # unset (see screening_prompt_pipeline.py), same pattern as company_name.
    ai_agent_name: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    # Structured requirement strings — the JD-matching rubric scores candidates
    # against each entry individually (spec section 9.3: per-requirement evidence).
    requirements: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    employment_type: Mapped[EmploymentType] = mapped_column(
        str_enum_column(EmploymentType, 20), default=EmploymentType.FULL_TIME, nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        str_enum_column(JobStatus, 20), default=JobStatus.DRAFT, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
