from __future__ import annotations

from app.ai_employees.hr.integrations.calendar_provider import CalendarProvider
from app.ai_employees.hr.integrations.google_calendar_provider import GoogleCalendarProvider


def get_calendar_provider() -> CalendarProvider:
    return GoogleCalendarProvider()
