from __future__ import annotations

from datetime import datetime

from app.shared.schemas.base import CamelModel


class ScreeningResponse(CamelModel):
    id: str
    candidate_id: str
    status: str
    external_call_ref: str | None
    result_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None


class CompleteScreeningRequest(CamelModel):
    result_summary: str | None = None
