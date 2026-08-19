from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id


class Session(Base, TimestampMixin):
    """A login session. One refresh-token rotation family per session."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.SESSION)
    )
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Active organization context for this session; NULL until the user selects one.
    organization_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base, TimestampMixin):
    """Only the hash of the raw token is stored — see shared.security.hashing."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.REFRESH_TOKEN)
    )
    session_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when this token is rotated out for a newer one — lets us detect reuse of a
    # revoked token (a strong signal of theft) and revoke the whole session family.
    replaced_by_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
