"""Real SMTP implementation via the stdlib smtplib, wrapped in
asyncio.to_thread since smtplib has no native async API — avoids adding a
new async-SMTP dependency for a single-shot send.

Never silently no-ops: missing configuration or a send failure both raise,
so callers (see app.ai_employees.hr.notifications.interview_notifier) can
never report a notification as sent when it wasn't (spec sections 19, 21 —
"do not falsely claim emails were sent").
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppError
from app.shared.notifications.email_sender import EmailSender


class EmailNotConfiguredError(AppError):
    status_code = 503
    code = ErrorCode.INTERNAL_ERROR


class SmtpEmailSender(EmailSender):
    async def send(self, *, to: list[str], subject: str, body: str) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            raise EmailNotConfiguredError(
                "SMTP_HOST is not configured — cannot send email. This must propagate as "
                "a real failure, not a silently-skipped send."
            )

        message = EmailMessage()
        message["From"] = settings.email_from_address
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message.set_content(body)

        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        settings = get_settings()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            client.send_message(message)
