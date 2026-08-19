from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class InterviewStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


INTERVIEW_TRANSITIONS = StateMachine[InterviewStatus](
    {
        InterviewStatus.PENDING_APPROVAL: frozenset(
            {InterviewStatus.APPROVED, InterviewStatus.CANCELLED}
        ),
        InterviewStatus.APPROVED: frozenset(
            {InterviewStatus.SCHEDULED, InterviewStatus.CANCELLED}
        ),
        InterviewStatus.SCHEDULED: frozenset(
            {InterviewStatus.COMPLETED, InterviewStatus.CANCELLED}
        ),
        InterviewStatus.COMPLETED: frozenset(),
        InterviewStatus.CANCELLED: frozenset(),
    }
)


class Interview(Base, OrgScopedMixin):
    __tablename__ = "interviews"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.INTERVIEW)
    )
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    screening_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("screenings.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[InterviewStatus] = mapped_column(
        str_enum_column(InterviewStatus, 20),
        default=InterviewStatus.PENDING_APPROVAL,
        nullable=False,
    )
    scheduled_slot_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("schedule_slots.id", ondelete="SET NULL"), nullable=True
    )
    meeting_link: Mapped[str | None] = mapped_column(String(500))
    interviewer_user_id: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
