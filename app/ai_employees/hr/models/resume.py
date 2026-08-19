from __future__ import annotations

from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.state_machine import StateMachine


class ResumeProcessingStatus(StrEnum):
    """Spec section 9.2."""

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    STORED = "stored"
    OCR_PROCESSING = "ocr_processing"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    # Extraction succeeded but the extracted profile has no usable name/email
    # (see app.ai_employees.hr.workflows.resume_pipeline._identity_issues) —
    # the pipeline cannot create a Candidate from untrusted, unusable
    # identity data, so it pauses here until HR supplies/corrects it via
    # POST /hr/resumes/{id}/confirm-identity.
    NEEDS_IDENTITY_REVIEW = "needs_identity_review"
    NORMALIZING = "normalizing"
    MATCHING = "matching"
    COMPLETED = "completed"
    PROCESSING_FAILED = "processing_failed"
    EXTRACTION_FAILED = "extraction_failed"
    MATCHING_FAILED = "matching_failed"


RESUME_TRANSITIONS = StateMachine[ResumeProcessingStatus](
    {
        ResumeProcessingStatus.UPLOADED: frozenset({ResumeProcessingStatus.VALIDATING}),
        ResumeProcessingStatus.VALIDATING: frozenset(
            {ResumeProcessingStatus.STORED, ResumeProcessingStatus.PROCESSING_FAILED}
        ),
        ResumeProcessingStatus.STORED: frozenset({ResumeProcessingStatus.OCR_PROCESSING}),
        ResumeProcessingStatus.OCR_PROCESSING: frozenset(
            {ResumeProcessingStatus.PARSING, ResumeProcessingStatus.PROCESSING_FAILED}
        ),
        ResumeProcessingStatus.PARSING: frozenset(
            {ResumeProcessingStatus.EXTRACTING, ResumeProcessingStatus.PROCESSING_FAILED}
        ),
        ResumeProcessingStatus.EXTRACTING: frozenset(
            {
                ResumeProcessingStatus.NORMALIZING,
                ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW,
                ResumeProcessingStatus.EXTRACTION_FAILED,
            }
        ),
        # HR confirming/correcting identity (ResumeService.confirm_identity)
        # is what moves this forward — never automatic.
        ResumeProcessingStatus.NEEDS_IDENTITY_REVIEW: frozenset(
            {ResumeProcessingStatus.NORMALIZING}
        ),
        ResumeProcessingStatus.NORMALIZING: frozenset(
            {ResumeProcessingStatus.MATCHING, ResumeProcessingStatus.EXTRACTION_FAILED}
        ),
        ResumeProcessingStatus.MATCHING: frozenset(
            {ResumeProcessingStatus.COMPLETED, ResumeProcessingStatus.MATCHING_FAILED}
        ),
        ResumeProcessingStatus.COMPLETED: frozenset(),
        # Retryable failures re-enter the stage that failed (spec section 9.2).
        ResumeProcessingStatus.PROCESSING_FAILED: frozenset(
            {ResumeProcessingStatus.OCR_PROCESSING}
        ),
        ResumeProcessingStatus.EXTRACTION_FAILED: frozenset({ResumeProcessingStatus.EXTRACTING}),
        ResumeProcessingStatus.MATCHING_FAILED: frozenset({ResumeProcessingStatus.MATCHING}),
    }
)


class Resume(Base, OrgScopedMixin):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.RESUME)
    )
    # Known at upload time (HR picks the job before dragging in a file) and
    # is the pipeline's only route to the job's requirements before a
    # Candidate exists — see JobRepository usage in resume_pipeline.py.
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("hr_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: the Candidate is only created once AI extraction produces a
    # usable name/email (or HR supplies one via confirm-identity) — a resume
    # can legitimately sit in NEEDS_IDENTITY_REVIEW with no candidate yet.
    candidate_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ResumeProcessingStatus] = mapped_column(
        str_enum_column(ResumeProcessingStatus, 30),
        default=ResumeProcessingStatus.UPLOADED,
        nullable=False,
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    # Persisted (not just held in-memory during one pipeline run) so a retry
    # that re-enters at the MATCHING stage — see RESUME_TRANSITIONS — can
    # reload the profile without re-running EXTRACTING.
    extracted_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
