from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.api.dependencies import require_voice_role
from app.ai_employees.voice.models.credit_transaction import CreditTransaction
from app.ai_employees.voice.models.recharge_order import RechargeOrder
from app.ai_employees.voice.models.recharge_package import RechargePackage
from app.ai_employees.voice.repositories.credit_ledger_repository import CreditLedgerRepository
from app.ai_employees.voice.repositories.recharge_repository import (
    RechargeOrderRepository,
    RechargePackageRepository,
)
from app.ai_employees.voice.schemas.credits import (
    CreateRechargeRequest,
    CreditBalanceResponse,
    CreditTransactionResponse,
    RechargeOrderResponse,
    RechargePackageResponse,
)
from app.ai_employees.voice.services.credit_ledger_service import CreditLedgerService
from app.ai_employees.voice.services.recharge_service import RechargeService
from app.billing.providers.base import PaymentProvider
from app.billing.providers.factory import get_payment_provider
from app.billing.repositories.payment_event_repository import PaymentEventRepository
from app.core.config import get_settings
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import OrgRole
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/jaan", tags=["Jaan Voice Credits"])

_READ_ROLES = (OrgRole.CUSTOMER_VOICE_USER, OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER)
_RECHARGE_ROLES = (OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER)


def _to_transaction_response(t: CreditTransaction) -> CreditTransactionResponse:
    return CreditTransactionResponse(
        id=t.id,
        type=t.type,
        minutes=t.minutes,
        amount=float(t.amount) if t.amount is not None else None,
        currency=t.currency,
        reference=t.reference,
        reason=t.reason,
        call_id=t.call_id,
        recharge_order_id=t.recharge_order_id,
        created_by_user_id=t.created_by_user_id,
        created_at=t.created_at,
    )


def _to_package_response(p: RechargePackage) -> RechargePackageResponse:
    return RechargePackageResponse(
        id=p.id,
        label=p.label,
        minutes=p.minutes,
        amount=float(p.amount),
        currency=p.currency,
        is_active=p.is_active,
        display_order=p.display_order,
    )


def _to_order_response(
    order: RechargeOrder, *, checkout_url: str | None = None
) -> RechargeOrderResponse:
    return RechargeOrderResponse(
        id=order.id,
        package_id=order.package_id,
        minutes=order.minutes,
        amount=float(order.amount),
        currency=order.currency,
        status=order.status,
        checkout_url=checkout_url,
        created_at=order.created_at,
        paid_at=order.paid_at,
    )


def _ledger_service(db: AsyncSession = Depends(get_db)) -> CreditLedgerService:
    return CreditLedgerService(CreditLedgerRepository(db))


def _recharge_service(
    db: AsyncSession = Depends(get_db),
    payment_provider: PaymentProvider = Depends(get_payment_provider),
) -> RechargeService:
    return RechargeService(
        db,
        RechargePackageRepository(db),
        RechargeOrderRepository(db),
        PaymentEventRepository(db),
        CreditLedgerService(CreditLedgerRepository(db)),
        payment_provider,
    )


@router.get("/credits", response_model=CreditBalanceResponse)
async def get_credit_balance(
    auth: AuthContext = Depends(require_voice_role(*_READ_ROLES)),
    service: CreditLedgerService = Depends(_ledger_service),
) -> CreditBalanceResponse:
    settings = get_settings()
    summary = await service.get_summary(
        auth.require_organization_id(),
        low_balance_threshold_minutes=settings.voice_low_balance_threshold_minutes,
    )
    return CreditBalanceResponse(
        balance_minutes=summary["balance_minutes"],
        low_balance=summary["low_balance"],
        low_balance_threshold_minutes=settings.voice_low_balance_threshold_minutes,
        purchased_minutes=summary["purchased_minutes"],
        used_minutes=summary["used_minutes"],
        last_recharge_at=summary["last_recharge_at"],
    )


@router.get("/credits/transactions", response_model=list[CreditTransactionResponse])
async def list_credit_transactions(
    auth: AuthContext = Depends(require_voice_role(*_READ_ROLES)),
    service: CreditLedgerService = Depends(_ledger_service),
) -> list[CreditTransactionResponse]:
    transactions = await service.list_transactions(auth.require_organization_id())
    return [_to_transaction_response(t) for t in transactions]


@router.get("/recharge/packages", response_model=list[RechargePackageResponse])
async def list_recharge_packages(
    _auth: AuthContext = Depends(require_voice_role(*_READ_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[RechargePackageResponse]:
    # Deliberately not wired through RechargeService/PaymentProvider — a
    # plain catalog read has no reason to depend on live payment-provider
    # configuration being valid.
    packages = await RechargePackageRepository(db).list_active()
    return [_to_package_response(p) for p in packages]


@router.post("/recharge", response_model=RechargeOrderResponse, status_code=201)
async def create_recharge(
    payload: CreateRechargeRequest,
    auth: AuthContext = Depends(require_voice_role(*_RECHARGE_ROLES)),
    service: RechargeService = Depends(_recharge_service),
) -> RechargeOrderResponse:
    order, checkout_url = await service.create_recharge_order(
        auth.require_organization_id(),
        package_id=payload.package_id,
        customer_email=auth.user.email,
        created_by_user_id=auth.user.id,
    )
    return _to_order_response(order, checkout_url=checkout_url)


@router.get("/recharge/{order_id}", response_model=RechargeOrderResponse)
async def get_recharge_order(
    order_id: str,
    auth: AuthContext = Depends(require_voice_role(*_READ_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> RechargeOrderResponse:
    order = await RechargeOrderRepository(db).get_by_id(auth.require_organization_id(), order_id)
    if order is None:
        raise NotFoundError("Recharge order not found.")
    return _to_order_response(order)


@router.get("/recharge", response_model=list[RechargeOrderResponse])
async def list_recharge_orders(
    auth: AuthContext = Depends(require_voice_role(*_READ_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[RechargeOrderResponse]:
    orders = await RechargeOrderRepository(db).list_for_organization(auth.require_organization_id())
    return [_to_order_response(o) for o in orders]
