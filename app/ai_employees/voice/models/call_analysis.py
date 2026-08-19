from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id


class CallAnalysis(Base, OrgScopedMixin):
    """Structured, schema-validated post-call analysis (spec sections 10.1,
    41) — never persisted from raw model text; see
    app.ai_employees.voice.schemas.analysis.CallAnalysisResult, which is
    validated before a row is ever written here (same posture as HR's
    Assessment — app.ai_employees.hr.models.assessment).
    """

    __tablename__ = "call_analyses"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CALL_ANALYSIS)
    )
    call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    intent_detected: Mapped[str | None] = mapped_column(String(120))
    sentiment: Mapped[str | None] = mapped_column(String(30))
    resolution_status: Mapped[str | None] = mapped_column(String(60))
    summary: Mapped[str | None] = mapped_column(Text)
    key_topics: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
