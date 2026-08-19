from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id


class CallUsage(Base, OrgScopedMixin):
    """Metering and cost tracking for Voice calls (spec section 36).

    Captures LLM token counts, STT audio seconds, TTS characters, telephony
    minutes, and calculated cost per call.
    """

    __tablename__ = "call_usages"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CALL_USAGE)
    )
    call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(60), default="openai", nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stt_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tts_characters: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    telephony_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Numeric(10, 4), default=0.0, nullable=False)
