from __future__ import annotations

from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class AssessmentKind(StrEnum):
    JD_MATCH = "jd_match"


class Assessment(Base, OrgScopedMixin):
    """Structured, evidence-backed AI scoring output (spec section 9.3).

    Never persisted from raw model text — only from output already
    validated against ``app.ai_employees.hr.schemas.assessment.JdMatchResult``
    (spec section 41: AI output is untrusted input until schema-validated).
    """

    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.ASSESSMENT)
    )
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AssessmentKind] = mapped_column(
        str_enum_column(AssessmentKind, 20), default=AssessmentKind.JD_MATCH, nullable=False
    )
    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    skill_match: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    experience_match: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    missing_requirements: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(20), nullable=False)
