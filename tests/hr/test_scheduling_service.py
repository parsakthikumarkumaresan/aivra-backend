"""Service-level tests for SchedulingService's interviewer-panelist and
notification wiring (spec sections 16-19, 21): manual panelist emails are
persisted, candidate email is auto-derived (never a request field), a
meeting link is only ever real (never faked) when a calendar integration
exists, and notification "sent" status always reflects an actual send
attempt outcome — never falsely reported.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage
from app.ai_employees.hr.models.integration import CalendarIntegration, IntegrationProvider
from app.ai_employees.hr.models.interview import Interview, InterviewStatus
from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.models.schedule_slot import ScheduleSlot
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.integration_repository import IntegrationRepository
from app.ai_employees.hr.repositories.interview_panelist_repository import (
    InterviewPanelistRepository,
)
from app.ai_employees.hr.repositories.interview_repository import InterviewRepository
from app.ai_employees.hr.repositories.schedule_slot_repository import ScheduleSlotRepository
from app.ai_employees.hr.services.scheduling_service import SchedulingService
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.shared.security.passwords import hash_password
from tests.fakes.fake_hr_integrations import (
    FakeCalendarProvider,
    FakeEmailSender,
    UnconfiguredEmailSender,
)


def _service(
    db_session: AsyncSession, *, calendar_provider: FakeCalendarProvider, email_sender
) -> SchedulingService:
    return SchedulingService(
        InterviewRepository(db_session),
        ScheduleSlotRepository(db_session),
        CandidateRepository(db_session),
        CandidateIdentityRepository(db_session),
        IntegrationRepository(db_session),
        calendar_provider,
        InterviewPanelistRepository(db_session),
        email_sender,
    )


async def _seed_approved_interview(
    db_session: AsyncSession, *, slug: str, with_calendar_integration: bool
) -> tuple[Organization, Candidate, ScheduleSlot]:
    org = Organization(name="Acme", slug=slug)
    db_session.add(org)
    await db_session.flush()

    user = User(
        email=f"hr-{slug}@example.com",
        password_hash=hash_password("SuperSecret123!"),
        full_name="HR Admin",
    )
    db_session.add(user)
    await db_session.flush()

    job = HrJob(
        organization_id=org.id,
        created_by_user_id=user.id,
        title="Backend Engineer",
        company_name="Acme Corp",
        requirements=["Python"],
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    await db_session.flush()

    identity = CandidateIdentity(
        organization_id=org.id,
        full_name="Jane Doe",
        email=f"jane-{slug}@example.com",
        phone="555-0100",
    )
    db_session.add(identity)
    await db_session.flush()

    candidate = Candidate(
        organization_id=org.id,
        job_id=job.id,
        identity_id=identity.id,
        stage=CandidateStage.INTERVIEW_PENDING,
    )
    db_session.add(candidate)
    await db_session.flush()

    db_session.add(
        Interview(
            organization_id=org.id, candidate_id=candidate.id, status=InterviewStatus.APPROVED
        )
    )

    slot = ScheduleSlot(
        organization_id=org.id,
        interviewer_user_id=user.id,
        start_time=datetime.now(UTC) + timedelta(days=1),
        end_time=datetime.now(UTC) + timedelta(days=1, hours=1),
    )
    db_session.add(slot)
    await db_session.flush()

    if with_calendar_integration:
        db_session.add(
            CalendarIntegration(
                organization_id=org.id,
                provider=IntegrationProvider.GOOGLE_CALENDAR,
                access_token="fake-access-token",
            )
        )
        await db_session.flush()

    return org, candidate, slot


async def test_book_slot_persists_manually_entered_panelist_emails(
    db_session: AsyncSession,
) -> None:
    org, candidate, slot = await _seed_approved_interview(
        db_session, slug="panelists", with_calendar_integration=True
    )
    calendar = FakeCalendarProvider()
    email_sender = FakeEmailSender()
    service = _service(db_session, calendar_provider=calendar, email_sender=email_sender)

    interview = await service.book_slot(
        org.id,
        slot.id,
        candidate.id,
        job_title="Backend Engineer",
        company_name="Acme Corp",
        panelist_emails=["lead@acme.test", "manager@acme.test"],
    )

    panelists = await InterviewPanelistRepository(db_session).list_for_interview(
        org.id, interview.id
    )
    assert {p.email for p in panelists} == {"lead@acme.test", "manager@acme.test"}
    # Candidate email came from the candidate record, never from the request.
    assert calendar.calls[0]["attendee_emails"][0].startswith("jane-panelists@")
    assert "lead@acme.test" in calendar.calls[0]["attendee_emails"]


async def test_book_slot_meeting_link_absent_without_calendar_integration(
    db_session: AsyncSession,
) -> None:
    org, candidate, slot = await _seed_approved_interview(
        db_session, slug="no-calendar", with_calendar_integration=False
    )
    calendar = FakeCalendarProvider()
    email_sender = FakeEmailSender()
    service = _service(db_session, calendar_provider=calendar, email_sender=email_sender)

    interview = await service.book_slot(
        org.id, slot.id, candidate.id, job_title="Backend Engineer"
    )

    assert interview.meeting_link is None
    assert calendar.calls == []  # never called — no integration to call it with


async def test_book_slot_notification_status_reflects_real_send_outcomes(
    db_session: AsyncSession,
) -> None:
    org, candidate, slot = await _seed_approved_interview(
        db_session, slug="notify-mixed", with_calendar_integration=True
    )
    calendar = FakeCalendarProvider()
    identity_email = "jane-notify-mixed@example.com"
    email_sender = FakeEmailSender(fail_for={"bad-panelist@acme.test"})
    service = _service(db_session, calendar_provider=calendar, email_sender=email_sender)

    interview = await service.book_slot(
        org.id,
        slot.id,
        candidate.id,
        job_title="Backend Engineer",
        panelist_emails=["good-panelist@acme.test", "bad-panelist@acme.test"],
    )

    # Candidate email actually sent successfully.
    assert interview.candidate_notified_at is not None
    assert any(call["to"] == [identity_email] for call in email_sender.sent)

    panelists = await InterviewPanelistRepository(db_session).list_for_interview(
        org.id, interview.id
    )
    by_email = {p.email: p for p in panelists}
    assert by_email["good-panelist@acme.test"].notified_at is not None
    # The simulated failure must NOT be reported as notified.
    assert by_email["bad-panelist@acme.test"].notified_at is None


async def test_book_slot_never_falsely_reports_sent_when_email_unconfigured(
    db_session: AsyncSession,
) -> None:
    org, candidate, slot = await _seed_approved_interview(
        db_session, slug="unconfigured-smtp", with_calendar_integration=True
    )
    calendar = FakeCalendarProvider()
    service = _service(
        db_session, calendar_provider=calendar, email_sender=UnconfiguredEmailSender()
    )

    interview = await service.book_slot(
        org.id,
        slot.id,
        candidate.id,
        job_title="Backend Engineer",
        panelist_emails=["lead@acme.test"],
    )

    # Booking still succeeds (the interview itself is real and useful even
    # if notifications can't be sent) but nothing is falsely marked notified.
    assert interview.status == InterviewStatus.SCHEDULED
    assert interview.candidate_notified_at is None
    panelists = await InterviewPanelistRepository(db_session).list_for_interview(
        org.id, interview.id
    )
    assert all(p.notified_at is None for p in panelists)
