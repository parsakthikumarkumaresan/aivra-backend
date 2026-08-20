"""In-memory CalendarProvider/EmailSender fakes for scheduling-service tests
— no network calls, deterministic behavior, and a way to simulate failures
per-recipient without needing real SMTP/Google Calendar credentials.
"""

from __future__ import annotations

from datetime import datetime

from app.ai_employees.hr.integrations.calendar_provider import CalendarEvent, CalendarProvider
from app.shared.notifications.email_sender import EmailSender


class FakeCalendarProvider(CalendarProvider):
    def __init__(self, *, meeting_link: str = "https://meet.example.test/fake-room") -> None:
        self.meeting_link = meeting_link
        self.calls: list[dict] = []

    async def create_event(
        self,
        *,
        access_token: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendee_emails: list[str],
    ) -> CalendarEvent:
        self.calls.append({"title": title, "attendee_emails": attendee_emails})
        return CalendarEvent(event_id="evt_fake_1", meeting_link=self.meeting_link)


class FakeEmailSender(EmailSender):
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.sent: list[dict] = []

    async def send(self, *, to: list[str], subject: str, body: str) -> None:
        if any(recipient in self.fail_for for recipient in to):
            raise RuntimeError(f"Simulated send failure for {to}")
        self.sent.append({"to": to, "subject": subject, "body": body})


class UnconfiguredEmailSender(EmailSender):
    """Mirrors SmtpEmailSender's honest behavior when SMTP_HOST is empty —
    always raises, never silently succeeds.
    """

    async def send(self, *, to: list[str], subject: str, body: str) -> None:
        raise RuntimeError("SMTP_HOST is not configured — cannot send email.")
