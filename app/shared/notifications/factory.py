from __future__ import annotations

from app.shared.notifications.email_sender import EmailSender
from app.shared.notifications.smtp_email_sender import SmtpEmailSender


def get_email_sender() -> EmailSender:
    return SmtpEmailSender()
