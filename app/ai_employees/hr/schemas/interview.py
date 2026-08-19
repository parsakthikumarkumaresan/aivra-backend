from __future__ import annotations

from datetime import datetime

from app.shared.schemas.base import CamelModel


class InterviewResponse(CamelModel):
    id: str
    candidate_id: str
    screening_id: str | None
    status: str
    scheduled_slot_id: str | None
    meeting_link: str | None
    interviewer_user_id: str | None
    notes: str | None


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


class CompleteInterviewRequest(CamelModel):
    notes: str | None = None
