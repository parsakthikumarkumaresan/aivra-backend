from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.ai_employees.voice.models.credit_transaction import CreditTransactionType
from app.ai_employees.voice.models.recharge_order import RechargeOrderStatus
from app.shared.schemas.base import CamelModel


class CreditBalanceResponse(CamelModel):
    balance_minutes: int
    low_balance: bool
    low_balance_threshold_minutes: int
    purchased_minutes: int
    used_minutes: int
    last_recharge_at: datetime | None


class CreditTransactionResponse(CamelModel):
    id: str
    type: CreditTransactionType
    minutes: int
    amount: float | None
    currency: str | None
    reference: str | None
    reason: str | None
    call_id: str | None
    recharge_order_id: str | None
    created_by_user_id: str | None
    created_at: datetime


class RechargePackageResponse(CamelModel):
    id: str
    label: str
    minutes: int
    amount: float
    currency: str
    is_active: bool
    display_order: int


class CreateRechargePackageRequest(CamelModel):
    label: str = Field(min_length=1, max_length=120)
    minutes: int = Field(gt=0)
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    display_order: int = 0


class UpdateRechargePackageRequest(CamelModel):
    label: str | None = None
    minutes: int | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = None
    is_active: bool | None = None
    display_order: int | None = None


class CreateRechargeRequest(CamelModel):
    package_id: str


class RechargeOrderResponse(CamelModel):
    id: str
    package_id: str | None
    minutes: int
    amount: float
    currency: str
    status: RechargeOrderStatus
    checkout_url: str | None = None
    created_at: datetime
    paid_at: datetime | None


# --- Admin-only ---


class AdminCreditsSummaryResponse(CamelModel):
    organization_id: str
    balance_minutes: int
    purchased_minutes: int
    used_minutes: int
    usage_percent: float
    last_recharge_at: datetime | None


ADMIN_ADJUSTMENT_TYPES = (
    CreditTransactionType.INITIAL_ALLOCATION,
    CreditTransactionType.RECHARGE,
    CreditTransactionType.COMPLIMENTARY,
    CreditTransactionType.ADMIN_ADJUSTMENT,
    CreditTransactionType.REFUND,
)


class AdminAddCreditsRequest(CamelModel):
    type: CreditTransactionType
    minutes: int
    reason: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(default=None, max_length=255)
