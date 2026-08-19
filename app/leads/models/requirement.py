from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id


class Requirement(Base, TimestampMixin):
    """A single collected requirement item for a VoiceProject's discovery
    phase — free-form key/value so the discovery process isn't hardcoded
    to a fixed questionnaire shape.
    """

    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.REQUIREMENT)
    )
    voice_project_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("voice_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
