from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.shared.schemas.base import CamelModel


class InterviewPanelistResponse(CamelModel):
    email: str
    name: str | None
    notified_at: datetime | None


class InterviewResponse(CamelModel):
    id: str
    candidate_id: str
    screening_id: str | None
    status: str
    scheduled_slot_id: str | None
    meeting_link: str | None
    interviewer_user_id: str | None
    notes: str | None
    candidate_notified_at: datetime | None
    # Populated by the API layer from InterviewPanelistRepository — not a
    # column on Interview itself. Defaults to [] for interviews without
    # panelists rather than requiring every call site to pass one.
    panelists: list[InterviewPanelistResponse] = Field(default_factory=list)
    # Denormalized from the booked ScheduleSlot (via scheduled_slot_id) so
    # the frontend doesn't need a second lookup for a booked interview's time.
    scheduled_start_time: datetime | None = None
    scheduled_end_time: datetime | None = None


class CalendarStatusResponse(CamelModel):
    connected: bool


class ScheduleSlotResponse(CamelModel):
    id: str
    interviewer_user_id: str
    start_time: datetime
    end_time: datetime
    is_booked: bool
    candidate_id: str | None


class CreateSlotRequest(CamelModel):
    interviewer_user_id: str
    start_time: datetime
    end_time: datetime


class BookSlotRequest(CamelModel):
    slot_id: str
    candidate_id: str
    # Candidate email is never a request field — auto-derived server-side
    # from the candidate record (spec section 16). Interviewer/panel emails
    # are manually entered by HR; multiple panelists are supported.
    panelist_emails: list[str] = Field(default_factory=list)


class CompleteInterviewRequest(CamelModel):
    notes: str | None = None
