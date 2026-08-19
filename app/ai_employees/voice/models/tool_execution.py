from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class ToolExecutionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    TIMEOUT = "timeout"


class ToolExecution(Base, OrgScopedMixin):
    """Spec section 13 exactly: call_id, tool_id, input, output, status,
    duration, error_code, timestamp. Safe execution metadata only — inputs/
    outputs here must never contain raw provider credentials (spec: "never
    expose secrets to the model" / "log safe execution metadata").
    """

    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.TOOL_EXECUTION)
    )
    call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False
    )
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[ToolExecutionStatus] = mapped_column(
        str_enum_column(ToolExecutionStatus, 20),
        default=ToolExecutionStatus.PENDING,
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
