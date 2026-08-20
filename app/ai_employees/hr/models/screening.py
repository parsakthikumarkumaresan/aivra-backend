from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
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

    # --- AI screening prompt (spec section 2-4: auto-generated, HR-editable, never blank) ---
    prompt_text: Mapped[str | None] = mapped_column(Text)
    prompt_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prompt_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prompt_edited_by_user_id: Mapped[str | None] = mapped_column(String(40))
    # Append-only list of {prompt_text, edited_at, edited_by_user_id, source} —
    # auditability for prompt edits without a separate history table (spec section 4).
    prompt_history: Mapped[list | None] = mapped_column(JSON)

    # --- LiveKit/SIP call plumbing (internal — never exposed in the public API response) ---
    livekit_room_name: Mapped[str | None] = mapped_column(String(120))
    livekit_dispatch_id: Mapped[str | None] = mapped_column(String(120))
    sip_call_participant_identity: Mapped[str | None] = mapped_column(String(120))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # --- Conversation + structured result (spec sections 12, 14) ---
    # List of {speaker, text, is_final, timestamp} turns, appended live during the call.
    transcript: Mapped[list | None] = mapped_column(JSON)
    # ScreeningResult schema (app/ai_employees/hr/schemas/screening_result.py) as JSON.
    result: Mapped[dict | None] = mapped_column(JSON)
