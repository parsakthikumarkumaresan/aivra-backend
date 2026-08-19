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
            {ResumeProcessingStatus.NORMALIZING, ResumeProcessingStatus.EXTRACTION_FAILED}
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
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
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
