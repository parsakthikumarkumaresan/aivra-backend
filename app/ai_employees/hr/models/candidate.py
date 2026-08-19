from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class CandidateSource(StrEnum):
    RESUME_UPLOAD = "resume_upload"
    MANUAL = "manual"
    REFERRAL = "referral"


class CandidateStage(StrEnum):
    """Spec section 43.3."""

    NEW = "new"
    PROCESSING = "processing"
    MATCHED = "matched"
    HR_REVIEW = "hr_review"
    SCREENING_APPROVED = "screening_approved"
    SCREENING = "screening"
    SCREENED = "screened"
    HUMAN_REVIEW = "human_review"
    INTERVIEW_PENDING = "interview_pending"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    COMPLETED = "completed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ON_HOLD = "on_hold"


def _build_candidate_transitions() -> dict[CandidateStage, frozenset[CandidateStage]]:
    forward_path = [
        CandidateStage.NEW,
        CandidateStage.PROCESSING,
        CandidateStage.MATCHED,
        CandidateStage.HR_REVIEW,
        CandidateStage.SCREENING_APPROVED,
        CandidateStage.SCREENING,
        CandidateStage.SCREENED,
        CandidateStage.HUMAN_REVIEW,
        CandidateStage.INTERVIEW_PENDING,
        CandidateStage.INTERVIEW_SCHEDULED,
        CandidateStage.COMPLETED,
    ]
    hold_eligible = {
        CandidateStage.HR_REVIEW,
        CandidateStage.SCREENING_APPROVED,
        CandidateStage.SCREENED,
        CandidateStage.HUMAN_REVIEW,
        CandidateStage.INTERVIEW_PENDING,
    }

    transitions: dict[CandidateStage, set[CandidateStage]] = {}
    for current, following in zip(forward_path, forward_path[1:], strict=False):
        transitions[current] = {following}
    for stage in forward_path[:-1]:  # every non-terminal forward stage can exit early
        transitions[stage].update({CandidateStage.REJECTED, CandidateStage.WITHDRAWN})
    for stage in hold_eligible:
        transitions[stage].add(CandidateStage.ON_HOLD)
    transitions[CandidateStage.ON_HOLD] = {CandidateStage.HR_REVIEW}
    transitions[CandidateStage.COMPLETED] = set()
    transitions[CandidateStage.REJECTED] = set()
    transitions[CandidateStage.WITHDRAWN] = set()

    return {stage: frozenset(targets) for stage, targets in transitions.items()}


CANDIDATE_TRANSITIONS = StateMachine[CandidateStage](_build_candidate_transitions())


class Candidate(Base, OrgScopedMixin):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CANDIDATE)
    )
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("hr_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[CandidateSource] = mapped_column(
        str_enum_column(CandidateSource, 20), default=CandidateSource.RESUME_UPLOAD, nullable=False
    )
    stage: Mapped[CandidateStage] = mapped_column(
        str_enum_column(CandidateStage, 30), default=CandidateStage.NEW, nullable=False
    )
    resume_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
