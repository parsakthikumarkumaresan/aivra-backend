from __future__ import annotations

from datetime import datetime

from app.shared.schemas.base import CamelModel


class PlanResponse(CamelModel):
    id: str
    employee_type: str
    code: str
    name: str
    billing_cycle: str
    price: float
    currency: str


class SubscriptionResponse(CamelModel):
    id: str
    employee_type: str
    status: str
    billing_cycle: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class HireEmployeeRequest(CamelModel):
    billing_cycle: str


class CheckoutResponse(CamelModel):
    subscription: SubscriptionResponse
    checkout_url: str


class ChangeBillingCycleRequest(CamelModel):
    billing_cycle: str


class InvoiceResponse(CamelModel):
    id: str
    status: str
    amount: float
    currency: str
    period_start: datetime
    period_end: datetime
    issued_at: datetime | None
    hosted_invoice_url: str | None


class BillingPortalResponse(CamelModel):
    portal_url: str
