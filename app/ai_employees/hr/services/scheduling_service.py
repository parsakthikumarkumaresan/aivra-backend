"""Interview creation, slot booking and calendar-event creation (spec
sections 9.1, 43.3; Definition of Done: "Interview scheduling creates a
valid meeting event/link").

Booking a slot succeeds even without a connected calendar integration —
the interview time itself is real and useful on its own; the meeting link
is best-effort and only populated once a CalendarIntegration exists (spec
section 41 MVP discipline: self-service OAuth connection is a follow-up,
see app.ai_employees.hr.models.integration).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.hr.integrations.calendar_provider import CalendarProvider
from app.ai_employees.hr.models.candidate import (
    CANDIDATE_TRANSITIONS,
    CandidateIdentity,
    CandidateStage,
)
from app.ai_employees.hr.models.integration import IntegrationProvider
from app.ai_employees.hr.models.interview import INTERVIEW_TRANSITIONS, Interview, InterviewStatus
from app.ai_employees.hr.models.interview_panelist import InterviewPanelist
from app.ai_employees.hr.models.schedule_slot import ScheduleSlot
from app.ai_employees.hr.notifications.interview_notifier import send_interview_invitations
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
from app.audit.models.audit_event import ActorType
from app.audit.services.audit_service import AuditService
from app.shared.errors.exceptions import ConflictError, NotFoundError
from app.shared.notifications.email_sender import EmailSender


class SchedulingService:
    def __init__(
        self,
        interview_repo: InterviewRepository,
        slot_repo: ScheduleSlotRepository,
        candidate_repo: CandidateRepository,
        identity_repo: CandidateIdentityRepository,
        integration_repo: IntegrationRepository,
        calendar_provider: CalendarProvider,
        panelist_repo: InterviewPanelistRepository,
        email_sender: EmailSender,
        audit: AuditService | None = None,
    ) -> None:
        self.interview_repo = interview_repo
        self.slot_repo = slot_repo
        self.candidate_repo = candidate_repo
        self.identity_repo = identity_repo
        self.integration_repo = integration_repo
        self.calendar_provider = calendar_provider
        self.panelist_repo = panelist_repo
        self.email_sender = email_sender
        self.audit = audit

    async def request_interview(self, organization_id: str, candidate_id: str) -> Interview:
        """Called from the candidate-level "Approve for Human Interview" Gate
        2 action (see CandidateService.approve_for_interview) — that HR
        decision *is* the real-world approval, and no separate UI step ever
        exists to call approve_interview() afterward. Create the Interview
        row and immediately promote it to APPROVED in the same action rather
        than leaving it stuck at PENDING_APPROVAL with no way to reach the
        state book_slot requires.
        """
        interview = await self.interview_repo.get_for_candidate(organization_id, candidate_id)
        if interview is None:
            interview = await self.interview_repo.add(
                Interview(
                    organization_id=organization_id,
                    candidate_id=candidate_id,
                    status=InterviewStatus.PENDING_APPROVAL,
                )
            )
        if interview.status != InterviewStatus.APPROVED:
            INTERVIEW_TRANSITIONS.assert_transition_allowed(
                interview.status, InterviewStatus.APPROVED
            )
            interview.status = InterviewStatus.APPROVED
        return interview

    async def approve_interview(self, organization_id: str, interview_id: str) -> Interview:
        interview = await self._require_interview(organization_id, interview_id)
        INTERVIEW_TRANSITIONS.assert_transition_allowed(interview.status, InterviewStatus.APPROVED)
        interview.status = InterviewStatus.APPROVED
        return interview

    async def create_slot(
        self,
        organization_id: str,
        interviewer_user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> ScheduleSlot:
        if end_time <= start_time:
            raise ConflictError("Slot end time must be after start time.")
        return await self.slot_repo.add(
            ScheduleSlot(
                organization_id=organization_id,
                interviewer_user_id=interviewer_user_id,
                start_time=start_time,
                end_time=end_time,
            )
        )

    async def list_available_slots(self, organization_id: str) -> list[ScheduleSlot]:
        return await self.slot_repo.list_available(organization_id)

    async def is_calendar_connected(self, organization_id: str) -> bool:
        integration = await self.integration_repo.get_for_provider(
            organization_id, IntegrationProvider.GOOGLE_CALENDAR
        )
        return integration is not None

    async def book_slot(
        self,
        organization_id: str,
        slot_id: str,
        candidate_id: str,
        *,
        job_title: str,
        company_name: str | None = None,
        panelist_emails: list[str] | None = None,
    ) -> Interview:
        slot = await self.slot_repo.get_by_id(organization_id, slot_id)
        if slot is None:
            raise NotFoundError("Schedule slot not found.")
        if slot.is_booked:
            raise ConflictError("This slot has already been booked.")

        interview = await self.interview_repo.get_for_candidate(organization_id, candidate_id)
        if interview is None or interview.status != InterviewStatus.APPROVED:
            raise ConflictError("Candidate has no approved interview ready to be scheduled.")

        candidate = await self.candidate_repo.get_by_id(organization_id, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        identity = await self.identity_repo.get_by_id(organization_id, candidate.identity_id)
        if identity is None:
            raise NotFoundError("Candidate identity not found.")

        slot.is_booked = True
        slot.candidate_id = candidate_id

        panelist_emails = [e.strip() for e in (panelist_emails or []) if e.strip()]
        meeting_link = await self._try_create_calendar_event(
            organization_id, slot, identity, job_title, panelist_emails
        )

        INTERVIEW_TRANSITIONS.assert_transition_allowed(interview.status, InterviewStatus.SCHEDULED)
        interview.status = InterviewStatus.SCHEDULED
        interview.scheduled_slot_id = slot.id
        interview.interviewer_user_id = slot.interviewer_user_id
        interview.meeting_link = meeting_link

        CANDIDATE_TRANSITIONS.assert_transition_allowed(
            candidate.stage, CandidateStage.INTERVIEW_SCHEDULED
        )
        candidate.stage = CandidateStage.INTERVIEW_SCHEDULED

        panelists = [
            await self.panelist_repo.add(
                InterviewPanelist(
                    organization_id=organization_id, interview_id=interview.id, email=email
                )
            )
            for email in panelist_emails
        ]

        results = await send_interview_invitations(
            self.email_sender,
            job_title=job_title,
            company_name=company_name,
            start_time_display=slot.start_time.isoformat(),
            meeting_link=meeting_link,
            candidate_email=identity.email,
            panelist_emails=panelist_emails,
        )
        now = datetime.now(UTC)
        if self.audit:
            await self.audit.record(
                organization_id=organization_id,
                actor_id=interview.interviewer_user_id or "SYSTEM",
                actor_type=ActorType.USER,
                action="INTERVIEW_SCHEDULED",
                resource_type="INTERVIEW",
                resource_id=interview.id,
            )

        if results.get(identity.email):
            interview.candidate_notified_at = now
            if self.audit:
                await self.audit.record(
                    organization_id=organization_id,
                    actor_id=interview.interviewer_user_id or "SYSTEM",
                    actor_type=ActorType.USER,
                    action="INTERVIEW_INVITATION_SENT",
                    resource_type="INTERVIEW",
                    resource_id=interview.id,
                )
        elif self.audit:
            await self.audit.record(
                organization_id=organization_id,
                actor_id=interview.interviewer_user_id or "SYSTEM",
                actor_type=ActorType.USER,
                action="INTERVIEW_INVITATION_FAILED",
                resource_type="INTERVIEW",
                resource_id=interview.id,
            )

        for panelist in panelists:
            if results.get(panelist.email):
                panelist.notified_at = now

        return interview

    async def resend_invitations(
        self,
        organization_id: str,
        interview_id: str,
        *,
        job_title: str = "Interview",
        company_name: str | None = None,
    ) -> Interview:
        """Retries sending email invitations for an already-scheduled interview
        without creating duplicate calendar slots or modifying booking status.
        """
        interview = await self._require_interview(organization_id, interview_id)
        if interview.status != InterviewStatus.SCHEDULED:
            raise ConflictError("Can only resend invitations for scheduled interviews.")

        candidate = await self.candidate_repo.get_by_id(organization_id, interview.candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        identity = await self.identity_repo.get_by_id(organization_id, candidate.identity_id)
        if identity is None:
            raise NotFoundError("Candidate identity not found.")

        slot = None
        if interview.scheduled_slot_id:
            slot = await self.slot_repo.get_by_id(organization_id, interview.scheduled_slot_id)

        start_time_display = slot.start_time.isoformat() if slot else datetime.now(UTC).isoformat()
        panelists = await self.panelist_repo.list_for_interview(organization_id, interview.id)
        panelist_emails = [p.email for p in panelists]

        results = await send_interview_invitations(
            self.email_sender,
            job_title=job_title,
            company_name=company_name,
            start_time_display=start_time_display,
            meeting_link=interview.meeting_link,
            candidate_email=identity.email,
            panelist_emails=panelist_emails,
        )
        now = datetime.now(UTC)
        if results.get(identity.email):
            interview.candidate_notified_at = now
            if self.audit:
                await self.audit.record(
                    organization_id=organization_id,
                    actor_id=interview.interviewer_user_id or "SYSTEM",
                    actor_type=ActorType.USER,
                    action="INTERVIEW_INVITATION_SENT",
                    resource_type="INTERVIEW",
                    resource_id=interview.id,
                )
        elif self.audit:
            await self.audit.record(
                organization_id=organization_id,
                actor_id=interview.interviewer_user_id or "SYSTEM",
                actor_type=ActorType.USER,
                action="INTERVIEW_INVITATION_FAILED",
                resource_type="INTERVIEW",
                resource_id=interview.id,
            )

        for panelist in panelists:
            if results.get(panelist.email):
                panelist.notified_at = now

        return interview

    async def _try_create_calendar_event(
        self,
        organization_id: str,
        slot: ScheduleSlot,
        identity: CandidateIdentity,
        job_title: str,
        panelist_emails: list[str],
    ) -> str | None:
        integration = await self.integration_repo.get_for_provider(
            organization_id, IntegrationProvider.GOOGLE_CALENDAR
        )
        if integration is None:
            return None
        event = await self.calendar_provider.create_event(
            access_token=integration.access_token,
            title=f"Interview: {identity.full_name} — {job_title}",
            start_time=slot.start_time,
            end_time=slot.end_time,
            attendee_emails=[identity.email, *panelist_emails],
        )
        return event.meeting_link

    async def complete_interview(
        self, organization_id: str, interview_id: str, *, notes: str | None
    ) -> Interview:
        interview = await self._require_interview(organization_id, interview_id)
        INTERVIEW_TRANSITIONS.assert_transition_allowed(interview.status, InterviewStatus.COMPLETED)
        interview.status = InterviewStatus.COMPLETED
        interview.notes = notes

        candidate = await self.candidate_repo.get_by_id(organization_id, interview.candidate_id)
        if candidate is not None:
            CANDIDATE_TRANSITIONS.assert_transition_allowed(
                candidate.stage, CandidateStage.COMPLETED
            )
            candidate.stage = CandidateStage.COMPLETED
        return interview

    async def cancel_interview(self, organization_id: str, interview_id: str) -> Interview:
        interview = await self._require_interview(organization_id, interview_id)
        INTERVIEW_TRANSITIONS.assert_transition_allowed(interview.status, InterviewStatus.CANCELLED)
        interview.status = InterviewStatus.CANCELLED
        return interview

    async def _require_interview(self, organization_id: str, interview_id: str) -> Interview:
        interview = await self.interview_repo.get_by_id(organization_id, interview_id)
        if interview is None:
            raise NotFoundError("Interview not found.")
        return interview
