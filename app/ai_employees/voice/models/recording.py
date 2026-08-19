from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class RecordingStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"


class Recording(Base, OrgScopedMixin):
    """Recording *metadata* only — the audio itself lives in the private
    recordings bucket (spec sections 22, 30); this row never stores a raw
    playback URL, only a storage key resolved to a signed URL on request.
    """

    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.RECORDING)
    )
    call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    storage_key: Mapped[str | None] = mapped_column(String(500))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[RecordingStatus] = mapped_column(
        str_enum_column(RecordingStatus, 20), default=RecordingStatus.PENDING, nullable=False
    )
