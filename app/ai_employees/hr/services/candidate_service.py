"""Candidate (per-job application) state transitions and lifecycle
management (spec sections 9.1, 43.3).

Every human-approval-gate action (approve/reject/hold/reconsider/archive/
restore) is recorded to the shared audit trail — these are exactly the
"consequential HR decisions" the Definition of Done requires human review
and evidence for.

Reconsider vs. Restore are deliberately different operations (see each
method's docstring): reconsider moves a REJECTED application back into the
recruitment workflow via the normal state machine; restore only changes
archival visibility and never touches `stage`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.hr.models.candidate import CANDIDATE_TRANSITIONS, Candidate, CandidateStage
from app.ai_employees.hr.repositories.candidate_identity_repository import (
    CandidateIdentityRepository,
)
from app.ai_employees.hr.repositories.candidate_repository import (
    CandidateRepository,
    CandidateVisibility,
)
from app.audit.models.audit_event import ActorType
from app.audit.services.audit_service import AuditService
from app.shared.errors.exceptions import ConflictError, InvalidStateTransitionError, NotFoundError


class CandidateService:
    def __init__(
        self,
        candidate_repo: CandidateRepository,
        identity_repo: CandidateIdentityRepository,
        audit: AuditService,
    ) -> None:
        self.candidate_repo = candidate_repo
        self.identity_repo = identity_repo
        self.audit = audit

    async def list_candidates(
        self,
        organization_id: str,
        *,
        job_id: str | None = None,
        stage: CandidateStage | None = None,
        source: str | None = None,
        search: str | None = None,
        visibility: CandidateVisibility = "active",
    ) -> list[Candidate]:
        return await self.candidate_repo.list_filtered(
            organization_id,
            job_id=job_id,
            stage=stage,
            source=source,
            search=search,
            visibility=visibility,
        )

    async def get_candidate(self, organization_id: str, candidate_id: str) -> Candidate:
        candidate = await self.candidate_repo.get_by_id(organization_id, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        return candidate

    async def _transition(
        self,
        organization_id: str,
        candidate_id: str,
        target_stage: CandidateStage,
        *,
        actor_id: str,
        action: str,
        reason: str | None = None,
        clear_reason: bool = False,
    ) -> Candidate:
        candidate = await self.get_candidate(organization_id, candidate_id)
        CANDIDATE_TRANSITIONS.assert_transition_allowed(candidate.stage, target_stage)
        candidate.stage = target_stage
        if reason is not None:
            candidate.rejected_reason = reason
        elif clear_reason:
            candidate.rejected_reason = None

        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action=action,
            resource_type="CANDIDATE",
            resource_id=candidate_id,
        )
        return candidate

    async def update_identity(
        self,
        organization_id: str,
        candidate_id: str,
        *,
        actor_id: str,
        full_name: str | None,
        email: str | None,
        phone: str | None,
    ) -> Candidate:
        """HR correcting AI-extracted identity during review (spec: 'HR
        Review / Correction'). Updates the shared CandidateIdentity — the
        correction applies to the *person*, and is therefore visible on
        every job application they have, not just this one.
        """
        candidate = await self.get_candidate(organization_id, candidate_id)
        identity = await self.identity_repo.get_by_id(organization_id, candidate.identity_id)
        if identity is None:
            raise NotFoundError("Candidate identity not found.")

        changed: dict[str, str] = {}
        if full_name is not None and full_name != identity.full_name:
            changed["fullName"] = full_name
            identity.full_name = full_name
        if email is not None and email != identity.email:
            changed["email"] = email
            identity.email = email
        if phone is not None and phone != identity.phone:
            changed["phone"] = phone
            identity.phone = phone

        if changed:
            await self.audit.record(
                organization_id=organization_id,
                actor_id=actor_id,
                actor_type=ActorType.USER,
                action="CANDIDATE_IDENTITY_CORRECTED",
                resource_type="CANDIDATE",
                resource_id=candidate_id,
            )
        return candidate

    async def approve_for_screening(
        self, organization_id: str, candidate_id: str, *, actor_id: str
    ) -> Candidate:
        return await self._transition(
            organization_id,
            candidate_id,
            CandidateStage.SCREENING_APPROVED,
            actor_id=actor_id,
            action="CANDIDATE_APPROVED_FOR_SCREENING",
        )

    async def reject(
        self, organization_id: str, candidate_id: str, *, actor_id: str, reason: str | None
    ) -> Candidate:
        return await self._transition(
            organization_id,
            candidate_id,
            CandidateStage.REJECTED,
            actor_id=actor_id,
            action="CANDIDATE_REJECTED",
            reason=reason,
        )

    async def hold(
        self, organization_id: str, candidate_id: str, *, actor_id: str, reason: str | None
    ) -> Candidate:
        return await self._transition(
            organization_id,
            candidate_id,
            CandidateStage.ON_HOLD,
            actor_id=actor_id,
            action="CANDIDATE_PUT_ON_HOLD",
            reason=reason,
        )

    async def approve_for_interview(
        self, organization_id: str, candidate_id: str, *, actor_id: str
    ) -> Candidate:
        return await self._transition(
            organization_id,
            candidate_id,
            CandidateStage.INTERVIEW_PENDING,
            actor_id=actor_id,
            action="CANDIDATE_APPROVED_FOR_INTERVIEW",
        )

    async def withdraw(
        self, organization_id: str, candidate_id: str, *, actor_id: str, reason: str | None
    ) -> Candidate:
        return await self._transition(
            organization_id,
            candidate_id,
            CandidateStage.WITHDRAWN,
            actor_id=actor_id,
            action="CANDIDATE_WITHDRAWN",
            reason=reason,
        )

    async def reconsider(
        self, organization_id: str, candidate_id: str, *, actor_id: str, note: str | None = None
    ) -> Candidate:
        """Explicit human action: REJECTED -> HR_REVIEW (spec: "Reconsider /
        Reopen"). Never automatic — resume re-upload only ever *reuses* the
        existing REJECTED Candidate row (see candidate_identity.py), it never
        calls this. The historical REJECTED decision stays in the audit
        trail forever; this only clears the *current* rejected_reason field
        since it no longer describes the application's live state.

        Requires the candidate to currently be REJECTED — the shared state
        machine's generic same-state no-op rule (StateMachine.can_transition)
        would otherwise let this "succeed" as a no-op from HR_REVIEW itself,
        or overload it as an unintended way to resume an ON_HOLD candidate
        (that transition exists in the table for a different reason). This
        is a distinct action from either of those.
        """
        candidate = await self.get_candidate(organization_id, candidate_id)
        if candidate.stage != CandidateStage.REJECTED:
            raise InvalidStateTransitionError(
                "Cannot reconsider a candidate that is not rejected "
                f"(current stage: {candidate.stage}).",
                details={"from": str(candidate.stage), "to": str(CandidateStage.HR_REVIEW)},
            )
        return await self._transition(
            organization_id,
            candidate_id,
            CandidateStage.HR_REVIEW,
            actor_id=actor_id,
            action="CANDIDATE_RECONSIDERED",
            clear_reason=True,
        )

    async def archive(self, organization_id: str, candidate_id: str, *, actor_id: str) -> Candidate:
        """Lifecycle visibility only — orthogonal to `stage`. An archived
        application keeps its stage/decisions/history exactly as they were;
        it's just hidden from the default active pipeline view.
        """
        candidate = await self.get_candidate(organization_id, candidate_id)
        if candidate.archived_at is not None:
            raise ConflictError("Candidate is already archived.")

        candidate.archived_at = datetime.now(UTC)
        candidate.archived_by_user_id = actor_id
        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action="CANDIDATE_ARCHIVED",
            resource_type="CANDIDATE",
            resource_id=candidate_id,
        )
        return candidate

    async def bulk_archive(
        self, organization_id: str, candidate_ids: list[str], *, actor_id: str
    ) -> tuple[list[Candidate], dict[str, str]]:
        """Archives only the candidates this call can actually find in this
        organization — tenant isolation is enforced by the same org-scoped
        lookup every other method uses, not a separate mechanism.
        """
        found_candidates = await self.candidate_repo.list_by_ids(organization_id, candidate_ids)
        found = {c.id: c for c in found_candidates}
        archived: list[Candidate] = []
        skipped: dict[str, str] = {}

        for candidate_id in candidate_ids:
            candidate = found.get(candidate_id)
            if candidate is None:
                skipped[candidate_id] = "not_found"
                continue
            if candidate.archived_at is not None:
                skipped[candidate_id] = "already_archived"
                continue
            candidate.archived_at = datetime.now(UTC)
            candidate.archived_by_user_id = actor_id
            await self.audit.record(
                organization_id=organization_id,
                actor_id=actor_id,
                actor_type=ActorType.USER,
                action="CANDIDATE_ARCHIVED",
                resource_type="CANDIDATE",
                resource_id=candidate_id,
            )
            archived.append(candidate)

        return archived, skipped

    async def restore(self, organization_id: str, candidate_id: str, *, actor_id: str) -> Candidate:
        """Archived -> active visibility only. Does NOT touch `stage` or any
        decision field — restoring a candidate must not "un-reject" them or
        restart their recruitment workflow (spec: use Reconsider for that).
        """
        candidate = await self.get_candidate(organization_id, candidate_id)
        if candidate.archived_at is None:
            raise ConflictError("Candidate is not archived.")

        candidate.archived_at = None
        candidate.archived_by_user_id = None
        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action="CANDIDATE_RESTORED",
            resource_type="CANDIDATE",
            resource_id=candidate_id,
        )
        return candidate
