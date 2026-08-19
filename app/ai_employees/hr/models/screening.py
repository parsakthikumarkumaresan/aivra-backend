from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class ScreeningStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Screening(Base, OrgScopedMixin):
    """An AI Voice screening call for a candidate.

    ``external_call_ref`` is an opaque string identifier for the Voice call
    (once the Voice bounded context exists) — deliberately NOT a foreign key
    to a Voice table. HR must never import Voice models/repositories (spec
    section 3.1); the two contexts communicate only through this kind of
    loose, ID-only reference plus shared platform events.
    """

    __tablename__ = "screenings"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.SCREENING)
    )
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScreeningStatus] = mapped_column(
        str_enum_column(ScreeningStatus, 20), default=ScreeningStatus.PENDING, nullable=False
    )
    external_call_ref: Mapped[str | None] = mapped_column(String(120))
    result_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
