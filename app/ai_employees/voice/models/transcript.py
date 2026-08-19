from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id


class Transcript(Base, OrgScopedMixin):
    """One row per call — ``turns`` is a JSON list of
    ``{id, speaker, text, timestamp}`` matching the frontend's
    ``TranscriptTurn`` shape exactly (spec section 15). Sensitive data
    (spec section 15): access is gated the same as the parent Call.
    """

    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.TRANSCRIPT)
    )
    call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    turns: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
