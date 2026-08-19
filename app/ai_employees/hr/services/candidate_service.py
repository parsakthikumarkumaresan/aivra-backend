"""Candidate pipeline state transitions (spec sections 9.1, 43.3).

Every human-approval-gate action (approve/reject/hold) is recorded to the
shared audit trail — these are exactly the "consequential HR decisions"
the Definition of Done requires human review and evidence for.
"""

from __future__ import annotations

from app.ai_employees.hr.models.candidate import CANDIDATE_TRANSITIONS, Candidate, CandidateStage
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.audit.models.audit_event import ActorType
from app.audit.services.audit_service import AuditService
from app.shared.errors.exceptions import NotFoundError


class CandidateService:
    def __init__(self, candidate_repo: CandidateRepository, audit: AuditService) -> None:
        self.candidate_repo = candidate_repo
        self.audit = audit

    async def list_candidates(
        self,
        organization_id: str,
        *,
        job_id: str | None = None,
        stage: CandidateStage | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> list[Candidate]:
        return await self.candidate_repo.list_filtered(
            organization_id, job_id=job_id, stage=stage, source=source, search=search
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
    ) -> Candidate:
        candidate = await self.get_candidate(organization_id, candidate_id)
        CANDIDATE_TRANSITIONS.assert_transition_allowed(candidate.stage, target_stage)
        candidate.stage = target_stage
        if reason is not None:
            candidate.rejected_reason = reason

        await self.audit.record(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            action=action,
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
