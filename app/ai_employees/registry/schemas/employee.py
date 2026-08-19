from __future__ import annotations

from app.shared.schemas.base import CamelModel


class EmployeeResponse(CamelModel):
    """Matches the frontend's ``AIEmployee`` type field-for-field.

    ``kpis`` is sourced from the analytics module once it ships (development
    sequence item 40); until then it is honestly empty rather than
    fabricated (spec section 47 — no fake completion).
    """

    id: str
    type: str
    name: str
    description: str | None
    status: str
    commercial_model: str
    base_price_monthly: float | None
    currency: str
    kpis: list[dict] = []


class EmployeeAccessResponse(CamelModel):
    employee_type: str
    status: str
    is_active: bool
