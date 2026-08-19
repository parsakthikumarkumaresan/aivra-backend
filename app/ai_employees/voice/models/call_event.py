from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id


class CallEvent(Base, OrgScopedMixin):
    """Normalized call lifecycle event log (spec section 19 DB group:
    ``call_events``) — room/participant/track events from LiveKit webhooks,
    plus application-level events (transfer initiated, tool invoked, etc.).
    """

    __tablename__ = "call_events"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CALL_EVENT)
    )
    call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
