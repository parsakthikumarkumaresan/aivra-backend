from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class CandidateIdentity(Base, OrgScopedMixin):
    """A person, within one tenant — reusable across every job they apply to.

    Deliberately separate from ``Candidate`` (below), which represents one
    person's recruitment relationship with one specific job. Without this
    split, "reject this person for Job A" and "this person is applying to
    Job B" could not be represented independently — see
    app.ai_employees.hr.services.candidate_identity for how the two combine.

    Scoped to one organization: the same email in two different
    organizations is two different, unrelated identities (spec section 7 —
    tenant isolation is never bypassed for deduplication).
    """

    __tablename__ = "candidate_identities"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CANDIDATE_IDENTITY)
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))


class CandidateSource(StrEnum):
    RESUME_UPLOAD = "resume_upload"
    MANUAL = "manual"
    REFERRAL = "referral"


class CandidateStage(StrEnum):
    """Spec section 43.3. Per-application (per-job) recruitment status —
    see CandidateIdentity above for the person-level identity this excludes.
    """

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
    # Explicit human "Reconsider / Reopen" action (never automatic — see
    # CandidateService.reconsider) is the only way out of REJECTED.
    transitions[CandidateStage.REJECTED] = {CandidateStage.HR_REVIEW}
    # A completed screening can conclude with the candidate simply having
    # been unavailable to talk (spec: not a technical failure) — HR must be
    # able to start a new screening call for the same application rather
    # than being stuck with no path back to SCREENING.
    transitions[CandidateStage.SCREENED].add(CandidateStage.SCREENING)
    # A completed screening advances straight through to HUMAN_REVIEW (see
    # ScreeningService.complete_screening/generate_result — there is no
    # separate manual "submit for review" action), so "Call Again" must
    # still be able to re-open a new screening call from there too, not
    # just from the fleeting SCREENED state it passes through.
    # HR can skip AI screening and directly approve the candidate for an interview
    # from HR_REVIEW or SCREENING_APPROVED (Path 2: HR Direct Interview path).
    transitions[CandidateStage.HR_REVIEW].add(CandidateStage.INTERVIEW_PENDING)
    transitions[CandidateStage.SCREENING_APPROVED].add(CandidateStage.INTERVIEW_PENDING)
    transitions[CandidateStage.COMPLETED] = set()
    transitions[CandidateStage.WITHDRAWN] = set()

    return {stage: frozenset(targets) for stage, targets in transitions.items()}


CANDIDATE_TRANSITIONS = StateMachine[CandidateStage](_build_candidate_transitions())


class Candidate(Base, OrgScopedMixin):
    """One person's recruitment relationship with one specific job — the
    per-job "application". ``identity_id`` links back to the shared person
    record (CandidateIdentity) so the same person can hold independent
    Candidate rows (independent stages, independent rejections) across
    multiple jobs without cross-contaminating each other.
    """

    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CANDIDATE)
    )
    identity_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("candidate_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("hr_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[CandidateSource] = mapped_column(
        str_enum_column(CandidateSource, 20), default=CandidateSource.RESUME_UPLOAD, nullable=False
    )
    stage: Mapped[CandidateStage] = mapped_column(
        str_enum_column(CandidateStage, 30), default=CandidateStage.NEW, nullable=False
    )
    resume_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    # Archival (lifecycle visibility) is orthogonal to `stage` (recruitment
    # progress) — a REJECTED or HR_REVIEW application can be archived and
    # later restored without touching its stage/decision history. See
    # CandidateService.archive/restore vs. reconsider.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
