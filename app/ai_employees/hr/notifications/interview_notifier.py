"""Interview-invitation email notifications (spec sections 19, 21).

Best-effort per recipient: one failed send must not silently claim success
for anyone else, and a recipient who wasn't actually notified must show
that honestly (see Interview.candidate_notified_at /
InterviewPanelist.notified_at) rather than a decorative "notified" badge.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.shared.notifications.email_sender import EmailSender

logger = get_logger(__name__)


async def send_interview_invitations(
    email_sender: EmailSender,
    *,
    job_title: str,
    company_name: str | None,
    start_time_display: str,
    meeting_link: str | None,
    candidate_email: str,
    panelist_emails: list[str],
) -> dict[str, bool]:
    """Sends one invitation per recipient. Returns {email: sent_ok} — never
    assumes success; each entry reflects an actual send attempt outcome.
    """
    subject = f"Interview scheduled: {job_title}"
    link_line = meeting_link or "Meeting link pending calendar connection — HR will follow up."
    company_line = f" at {company_name}" if company_name else ""
    body = (
        f"You have an interview scheduled for the {job_title} role{company_line}.\n\n"
        f"Time: {start_time_display}\n"
        f"Meeting link: {link_line}\n"
    )

    results: dict[str, bool] = {}
    for recipient in [candidate_email, *panelist_emails]:
        try:
            await email_sender.send(to=[recipient], subject=subject, body=body)
            results[recipient] = True
        except Exception:
            logger.exception("interview_invitation_send_failed", recipient=recipient)
            results[recipient] = False
    return results
