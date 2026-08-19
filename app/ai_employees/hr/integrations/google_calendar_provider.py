"""Google Calendar adapter via direct REST calls (Calendar API v3), same
posture as the Stripe/OpenAI adapters — real request shape, untested
against a live account (no OAuth flow wired up yet, see
app.ai_employees.hr.models.integration.CalendarIntegration). Requests a
Google Meet link via ``conferenceData`` so a real, joinable video link
comes back on success.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx

from app.ai_employees.hr.integrations.calendar_provider import CalendarEvent, CalendarProvider

_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarProvider(CalendarProvider):
    async def create_event(
        self,
        *,
        access_token: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendee_emails: list[str],
    ) -> CalendarEvent:
        request_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url=_CALENDAR_API_BASE, timeout=15.0) as client:
            response = await client.post(
                "/calendars/primary/events",
                params={"conferenceDataVersion": 1},
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "summary": title,
                    "start": {"dateTime": start_time.isoformat()},
                    "end": {"dateTime": end_time.isoformat()},
                    "attendees": [{"email": email} for email in attendee_emails],
                    "conferenceData": {
                        "createRequest": {
                            "requestId": request_id,
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                        }
                    },
                },
            )
            response.raise_for_status()
            body = response.json()

        meeting_link = body.get("hangoutLink")
        return CalendarEvent(event_id=body["id"], meeting_link=meeting_link)
