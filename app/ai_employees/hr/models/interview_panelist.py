"""Manually-entered interview panel members (spec section 16-19).

A separate child table rather than reusing ``Interview.interviewer_user_id``:
panelists are arbitrary HR-typed emails (internal interviewers who may not
have a platform user account), not FK-able ``users.id`` references.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id


class InterviewPanelist(Base, OrgScopedMixin):
    __tablename__ = "interview_panelists"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.INTERVIEW_PANELIST)
    )
    interview_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set only on an actual successful send — never faked (spec section 19).
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
