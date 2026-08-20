"""AI Voice screening call orchestration from HR's side (spec sections 1-4, 7).

A Screening row is created eagerly the first time HR opens a candidate's
screening (``ensure_screening``) — before any call is placed — so the
auto-generated prompt can be reviewed/edited ahead of "Start Screening".
``start_screening`` is the only place that actually places a call
(dispatches the RQ job in app.workers.jobs.hr_screening_jobs) and is
idempotent: a screening already ``IN_PROGRESS`` cannot be started twice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.hr.models.candidate import CANDIDATE_TRANSITIONS, Candidate, CandidateStage
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.workflows.screening_prompt_pipeline import generate_screening_prompt
from app.ai_employees.hr.workflows.screening_result_pipeline import generate_screening_result
from app.audit.models.audit_event import ActorType
from app.audit.services.audit_service import AuditService
from app.shared.errors.exceptions import ConflictError, NotFoundError

# Stages from which a screening may exist/start — anything earlier hasn't
# passed the human "Approve for AI Screening" gate yet (spec section 1).
_SCREENING_ELIGIBLE_STAGES = frozenset(
    {
        CandidateStage.SCREENING_APPROVED,
        CandidateStage.SCREENING,
        CandidateStage.SCREENED,
        CandidateStage.HUMAN_REVIEW,
        CandidateStage.INTERVIEW_PENDING,
        CandidateStage.INTERVIEW_SCHEDULED,
        CandidateStage.COMPLETED,
    }
)

# Only IN_PROGRESS blocks a new start — PENDING (prompt ready, call not yet
# placed) and FAILED (retryable) must both still allow Start Screening.
_BLOCKS_NEW_START = frozenset({ScreeningStatus.IN_PROGRESS})


class ScreeningService:
    def __init__(
        self,
        screening_repo: ScreeningRepository,
        candidate_repo: CandidateRepository,
        identity_repo: CandidateIdentityRepository,
        audit: AuditService,
    ) -> None:
        self.screening_repo = screening_repo
        self.candidate_repo = candidate_repo
        self.identity_repo = identity_repo
        self.audit = audit

    async def _get_eligible_candidate(self, organization_id: str, candidate_id: str) -> Candidate:
        candidate = await self.candidate_repo.get_by_id(organization_id, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        if candidate.stage not in _SCREENING_ELIGIBLE_STAGES:
            raise ConflictError("Candidate has not been approved for AI screening yet.")
        return candidate

    async def ensure_screening(self, organization_id: str, candidate_id: str) -> Screening:
        """Get-or-create the Screening row for a candidate. Does not move the
        candidate's stage or place a call — only Start Screening does that.
        """
        await self._get_eligible_candidate(organization_id, candidate_id)
        screening = await self.screening_repo.get_for_candidate(organization_id, candidate_id)
        if screening is not None:
            return screening
        return await self.screening_repo.add(
            Screening(
                organization_id=organization_id,
                candidate_id=candidate_id,
                status=ScreeningStatus.PENDING,
            )
        )

    async def generate_prompt(self, organization_id: str, candidate_id: str) -> Screening:
        """Auto-generates (or regenerates) the screening prompt. Raises
        ScreeningPromptGenerationError on any failure — callers must surface
        this to HR and must not fall back to a generic/fake prompt.
        """
        screening = await self.ensure_screening(organization_id, candidate_id)
        return await generate_screening_prompt(
            self.screening_repo.session,
            organization_id=organization_id,
            screening_id=screening.id,
        )

    async def get_or_generate_prompt(self, organization_id: str, candidate_id: str) -> Screening:
        """Lazy generation: only calls the LLM if no prompt exists yet, so
        re-opening an already-prompted screening doesn't re-spend tokens.
        """
        screening = await self.ensure_screening(organization_id, candidate_id)
        if (screening.prompt_text or "").strip():
            return screening
        return await self.generate_prompt(organization_id, candidate_id)

    async def update_prompt(
        self, organization_id: str, candidate_id: str, *, prompt_text: str, actor_id: str
    ) -> Screening:
        if not prompt_text.strip():
            raise ConflictError("Screening prompt cannot be blank.")
        screening = await self.screening_repo.get_for_candidate(organization_id, candidate_id)
        if screening is None:
            raise NotFoundError("No screening exists for this candidate.")

        now = datetime.now(UTC)
        screening.prompt_text = prompt_text
        screening.prompt_edited_at = now
        screening.prompt_edited_by_user_id = actor_id
        history = list(screening.prompt_history or [])
        history.append(
            {
                "promptText": prompt_text,
                "editedAt": now.isoformat(),
                "editedByUserId": actor_id,
                "source": "hr_edit",
            }
        )
        screening.prompt_history = history

        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action="SCREENING_PROMPT_EDITED",
            resource_type="SCREENING",
            resource_id=screening.id,
        )
        return screening

    async def start_screening(
        self, organization_id: str, candidate_id: str, *, actor_id: str
    ) -> Screening:
        candidate = await self._get_eligible_candidate(organization_id, candidate_id)
        screening = await self.screening_repo.get_for_candidate(organization_id, candidate_id)
        if screening is None or not (screening.prompt_text or "").strip():
            raise ConflictError(
                "Screening prompt has not been generated yet — open the screening "
                "before starting the call."
            )
        if screening.status in _BLOCKS_NEW_START:
            raise ConflictError("An active screening call already exists for this candidate.")

        identity = await self.identity_repo.get_by_id(organization_id, candidate.identity_id)
        if identity is None or not (identity.phone or "").strip():
            raise ConflictError("Candidate has no phone number on file — cannot place a call.")

        CANDIDATE_TRANSITIONS.assert_transition_allowed(candidate.stage, CandidateStage.SCREENING)
        candidate.stage = CandidateStage.SCREENING

        # A screening row is reused across attempts (spec: no duplicate
        # screening records) — that's safe for a retry after FAILED (no
        # transcript was ever captured), but starting a fresh call after a
        # previous attempt actually COMPLETED (e.g. the candidate was simply
        # unavailable last time) must not let the new conversation append
        # onto the old one. Clear the prior attempt's transcript/result only
        # in that case; a FAILED attempt's data (if any) is left untouched.
        if screening.status == ScreeningStatus.COMPLETED:
            screening.transcript = None
            screening.result = None
            screening.result_summary = None

        screening.status = ScreeningStatus.IN_PROGRESS
        screening.started_at = datetime.now(UTC)
        screening.failure_reason = None
        screening.completed_at = None

        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action="SCREENING_CALL_STARTED",
            resource_type="SCREENING",
            resource_id=screening.id,
        )
        return screening

    async def mark_dispatch_failed(
        self, organization_id: str, screening_id: str, *, reason: str
    ) -> Screening:
        """Called by the RQ job (app.workers.jobs.hr_screening_jobs) if
        placing the outbound call itself fails — keeps the failure honest and
        visible rather than leaving the screening stuck IN_PROGRESS forever.
        """
        screening = await self.screening_repo.get_by_id(organization_id, screening_id)
        if screening is None:
            raise NotFoundError("Screening not found.")
        screening.status = ScreeningStatus.FAILED
        screening.failure_reason = reason
        return screening

    async def generate_result(self, organization_id: str, candidate_id: str) -> Screening:
        """Defensive manual-recovery path — normally the agent process
        (app.ai_employees.hr.runtime.screening_agent) enqueues result
        generation automatically when a call ends. This exists for HR/ops
        to re-trigger it if that enqueue is ever missed.
        """
        screening = await self.screening_repo.get_for_candidate(organization_id, candidate_id)
        if screening is None:
            raise NotFoundError("No screening exists for this candidate.")

        updated = await generate_screening_result(
            self.screening_repo.session, organization_id=organization_id, screening_id=screening.id
        )
        if updated.status == ScreeningStatus.COMPLETED:
            candidate = await self.candidate_repo.get_by_id(organization_id, candidate_id)
            if candidate is not None and CANDIDATE_TRANSITIONS.can_transition(
                candidate.stage, CandidateStage.SCREENED
            ):
                candidate.stage = CandidateStage.SCREENED
                # See complete_screening's comment: advance straight through
                # to HUMAN_REVIEW in the same call — there is no separate
                # manual "submit for review" action, so a completed screening
                # must not leave the candidate stuck at SCREENED with no way
                # to reach the Gate 2 approval or scheduling UI.
                if CANDIDATE_TRANSITIONS.can_transition(
                    candidate.stage, CandidateStage.HUMAN_REVIEW
                ):
                    candidate.stage = CandidateStage.HUMAN_REVIEW
        return updated

    async def complete_screening(
        self, organization_id: str, candidate_id: str, *, result_summary: str | None
    ) -> Screening:
        screening = await self.screening_repo.get_for_candidate(organization_id, candidate_id)
        if screening is None:
            raise NotFoundError("No screening exists for this candidate.")

        candidate = await self.candidate_repo.get_by_id(organization_id, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")

        CANDIDATE_TRANSITIONS.assert_transition_allowed(candidate.stage, CandidateStage.SCREENED)
        candidate.stage = CandidateStage.SCREENED
        # A completed screening is immediately ready for HR's human-review
        # Gate 2 decision — there is no separate manual "submit for review"
        # action anywhere in the product, so advance straight through in the
        # same request rather than leaving every candidate stranded at
        # SCREENED with the Gate 2 approval / scheduling UI unreachable.
        CANDIDATE_TRANSITIONS.assert_transition_allowed(
            candidate.stage, CandidateStage.HUMAN_REVIEW
        )
        candidate.stage = CandidateStage.HUMAN_REVIEW

        screening.status = ScreeningStatus.COMPLETED
        screening.result_summary = result_summary
        screening.completed_at = datetime.now(UTC)
        return screening

    async def get_for_candidate(self, organization_id: str, candidate_id: str) -> Screening | None:
        return await self.screening_repo.get_for_candidate(organization_id, candidate_id)

    async def list_all(self, organization_id: str) -> list[Screening]:
        return await self.screening_repo.list_all(organization_id)
