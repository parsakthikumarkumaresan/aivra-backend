from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class IntegrationProvider(StrEnum):
    GOOGLE_CALENDAR = "google_calendar"


class CalendarIntegration(Base, OrgScopedMixin):
    """A connected external calendar account for interview scheduling.

    MVP scope note: this stores a token pair obtained out-of-band — there
    is no self-service "Sign in with Google" OAuth consent-screen flow yet
    (that's a real, separate feature: authorization-code exchange +
    callback routes). Documented here rather than silently pretended away
    (spec section 47). The actual Google Calendar API calls this backs are
    real (see app.ai_employees.hr.integrations.google_calendar_provider).
    """

    __tablename__ = "hr_calendar_integrations"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.INTEGRATION)
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        str_enum_column(IntegrationProvider, 30),
        default=IntegrationProvider.GOOGLE_CALENDAR,
        nullable=False,
    )
    access_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(String(2000))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
