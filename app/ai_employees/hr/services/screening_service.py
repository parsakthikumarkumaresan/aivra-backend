"""AI Voice screening call orchestration from HR's side (spec section 9.1).

Only ever references the Voice call by an opaque ``external_call_ref``
string — never a Voice model/repository import (spec section 3.1). The
actual call is placed by the Voice bounded context; HR just tracks the
screening's lifecycle and result.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.hr.models.candidate import CANDIDATE_TRANSITIONS, CandidateStage
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.shared.errors.exceptions import NotFoundError


class ScreeningService:
    def __init__(
        self, screening_repo: ScreeningRepository, candidate_repo: CandidateRepository
    ) -> None:
        self.screening_repo = screening_repo
        self.candidate_repo = candidate_repo

    async def start_screening(
        self, organization_id: str, candidate_id: str, *, external_call_ref: str | None = None
    ) -> Screening:
        candidate = await self.candidate_repo.get_by_id(organization_id, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")

        CANDIDATE_TRANSITIONS.assert_transition_allowed(candidate.stage, CandidateStage.SCREENING)
        candidate.stage = CandidateStage.SCREENING

        screening = await self.screening_repo.add(
            Screening(
                organization_id=organization_id,
                candidate_id=candidate_id,
                status=ScreeningStatus.IN_PROGRESS,
                external_call_ref=external_call_ref,
                started_at=datetime.now(UTC),
            )
        )
        return screening

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

        screening.status = ScreeningStatus.COMPLETED
        screening.result_summary = result_summary
        screening.completed_at = datetime.now(UTC)
        return screening

    async def get_for_candidate(self, organization_id: str, candidate_id: str) -> Screening | None:
        return await self.screening_repo.get_for_candidate(organization_id, candidate_id)

    async def list_all(self, organization_id: str) -> list[Screening]:
        return await self.screening_repo.list_all(organization_id)
