from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.shared.schemas.base import CamelModel


class QuoteCalculatorInputSchema(CamelModel):
    monthly_calls: int = Field(default=1000, ge=1, le=1000000)
    avg_call_duration_minutes: float = Field(default=2.5, gt=0, le=60.0)
    languages_count: int = Field(default=1, ge=1, le=50)
    workflow_complexity: str = Field(default="standard")
    integrations_count: int = Field(default=0, ge=0, le=50)
    custom_tools_count: int = Field(default=0, ge=0, le=50)
    knowledge_docs_count: int = Field(default=0, ge=0, le=5000)
    telephony_numbers_count: int = Field(default=1, ge=0, le=100)
    support_tier: str = Field(default="standard")
    currency: str = Field(default="INR", max_length=3)

    # Configurable pricing rules (Admin can configure or leave None to use baseline defaults)
    target_minute_rate: float | None = Field(default=None, ge=0)
    base_implementation_fee: float | None = Field(default=None, ge=0)
    base_platform_monthly_fee: float | None = Field(default=None, ge=0)
    fee_per_additional_language: float | None = Field(default=None, ge=0)
    fee_per_integration: float | None = Field(default=None, ge=0)


class QuoteSuggestedLineItemResponse(CamelModel):
    category: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    amount: float


class QuoteCalculationResponse(CamelModel):
    estimated_setup_fee: float
    estimated_recurring_fee: float
    estimated_total_monthly_minutes: int
    recommended_included_minutes: int
    indicative_minute_rate: float
    suggested_line_items: list[QuoteSuggestedLineItemResponse]
    calculation_breakdown: dict[str, Any]
    disclaimer: str


class QuoteLineItemCreateSchema(CamelModel):
    category: str = Field(default="other")
    description: str = Field(min_length=1, max_length=255)
    quantity: float = Field(default=1.0, gt=0)
    unit: str = Field(default="unit", max_length=50)
    unit_price: float = Field(default=0.0, ge=0)


class QuoteLineItemResponse(CamelModel):
    id: str
    category: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    amount: float
    display_order: int


class QuoteCreateRequest(CamelModel):
    organization_id: str
    title: str = Field(min_length=1, max_length=255)
    valid_until: datetime
    currency: str = Field(default="INR", max_length=3)
    lead_id: str | None = None
    voice_project_id: str | None = None
    notes: str | None = None
    terms: str | None = None
    discount: float = Field(default=0.0, ge=0)
    tax_rate: float = Field(default=0.0, ge=0, le=100)
    included_voice_minutes: int = Field(default=0, ge=0)
    additional_minute_rate: float = Field(default=0.0, ge=0)
    estimated_setup_fee: float | None = None
    estimated_recurring_fee: float | None = None
    calculation_snapshot: dict[str, Any] | None = None
    line_items: list[QuoteLineItemCreateSchema] = Field(default_factory=list)


class QuoteUpdateRequest(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    valid_until: datetime | None = None
    notes: str | None = None
    terms: str | None = None
    discount: float | None = Field(default=None, ge=0)
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    included_voice_minutes: int | None = Field(default=None, ge=0)
    additional_minute_rate: float | None = Field(default=None, ge=0)
    line_items: list[QuoteLineItemCreateSchema] | None = None


class QuoteSendRequest(CamelModel):
    recipient_email: str | None = None
    recipient_name: str | None = None


class QuoteTransitionRequest(CamelModel):
    target_status: str
    rejection_reason: str | None = None


class QuoteResponse(CamelModel):
    id: str
    organization_id: str
    lead_id: str | None
    voice_project_id: str | None
    quote_number: str
    title: str
    status: str
    currency: str
    subtotal: float
    discount: float
    tax_rate: float
    tax_amount: float
    total: float
    valid_until: datetime
    notes: str | None
    terms: str | None
    estimated_setup_fee: float | None
    estimated_recurring_fee: float | None
    included_voice_minutes: int
    additional_minute_rate: float
    calculation_snapshot: dict[str, Any] | None
    created_by_user_id: str | None
    sent_at: datetime | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    line_items: list[QuoteLineItemResponse]


class QuoteSendResponse(CamelModel):
    quote: QuoteResponse
    email_sent: bool
    email_error: str | None = None


class QuoteListResponse(CamelModel):
    items: list[QuoteResponse]
    total: int
    page: int
    page_size: int
