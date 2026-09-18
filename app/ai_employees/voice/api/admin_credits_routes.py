from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.credit_transaction import (
    CreditTransaction,
    CreditTransactionType,
)
from app.ai_employees.voice.models.recharge_order import RechargeOrder
from app.ai_employees.voice.models.recharge_package import RechargePackage
from app.ai_employees.voice.repositories.credit_ledger_repository import CreditLedgerRepository
from app.ai_employees.voice.repositories.recharge_repository import (
    RechargeOrderRepository,
    RechargePackageRepository,
)
from app.ai_employees.voice.schemas.credits import (
    ADMIN_ADJUSTMENT_TYPES,
    AdminAddCreditsRequest,
    AdminCreditsSummaryResponse,
    CreateRechargePackageRequest,
    CreditTransactionResponse,
    RechargeOrderResponse,
    RechargePackageResponse,
    UpdateRechargePackageRequest,
)
from app.ai_employees.voice.services.credit_ledger_service import CreditLedgerService
from app.audit.models.audit_event import ActorType
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError, ValidationAppError
from app.shared.rbac.roles import PlatformRole
from app.shared.security.dependencies import AuthContext
from app.shared.security.dependencies import require_platform_role as _require_platform_role

router = APIRouter(
    prefix="/internal/voice/admin",
    tags=["Jaan Voice Admin — Credits"],
    dependencies=[
        Depends(_require_platform_role(PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER))
    ],
)


def _ledger_service(db: AsyncSession = Depends(get_db)) -> CreditLedgerService:
    return CreditLedgerService(CreditLedgerRepository(db))


async def _require_organization(organization_id: str, db: AsyncSession) -> None:
    org = await OrganizationRepository(db).get_by_id(organization_id)
    if org is None:
        raise NotFoundError("Organization not found.")


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


def _to_order_response(order: RechargeOrder) -> RechargeOrderResponse:
    return RechargeOrderResponse(
        id=order.id,
        package_id=order.package_id,
        minutes=order.minutes,
        amount=float(order.amount),
        currency=order.currency,
        status=order.status,
        created_at=order.created_at,
        paid_at=order.paid_at,
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


@router.get(
    "/organizations/{organization_id}/credits",
    response_model=AdminCreditsSummaryResponse,
)
async def get_organization_credits(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> AdminCreditsSummaryResponse:
    await _require_organization(organization_id, db)
    repo = CreditLedgerRepository(db)
    balance = await repo.get_balance(organization_id)
    totals = await repo.get_totals(organization_id)
    last_recharge_at = await repo.get_last_recharge_at(organization_id)
    usage_percent = (totals["used"] / totals["purchased"] * 100) if totals["purchased"] > 0 else 0.0
    return AdminCreditsSummaryResponse(
        organization_id=organization_id,
        balance_minutes=balance,
        purchased_minutes=totals["purchased"],
        used_minutes=totals["used"],
        usage_percent=round(usage_percent, 1),
        last_recharge_at=last_recharge_at,
    )


@router.get(
    "/organizations/{organization_id}/credits/transactions",
    response_model=list[CreditTransactionResponse],
)
async def list_organization_transactions(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
    service: CreditLedgerService = Depends(_ledger_service),
) -> list[CreditTransactionResponse]:
    await _require_organization(organization_id, db)
    transactions = await service.list_transactions(organization_id, limit=500)
    return [_to_transaction_response(t) for t in transactions]


@router.post(
    "/organizations/{organization_id}/credits/adjust",
    response_model=CreditTransactionResponse,
    status_code=201,
)
async def adjust_organization_credits(
    organization_id: str,
    payload: AdminAddCreditsRequest,
    auth: AuthContext = Depends(
        _require_platform_role(PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER)
    ),
    db: AsyncSession = Depends(get_db),
    service: CreditLedgerService = Depends(_ledger_service),
) -> CreditTransactionResponse:
    """Every manual credit change is attributed to the acting admin
    (created_by_user_id) and reason, and mirrored into the platform audit
    log (spec sections 8, 13, 29) — never a silent DB write.
    """
    await _require_organization(organization_id, db)

    if payload.type not in ADMIN_ADJUSTMENT_TYPES:
        raise ValidationAppError("Unsupported credit transaction type for a manual adjustment.")
    if payload.minutes == 0:
        raise ValidationAppError("minutes must not be zero.")
    if (
        payload.type
        in (
            CreditTransactionType.INITIAL_ALLOCATION,
            CreditTransactionType.RECHARGE,
            CreditTransactionType.COMPLIMENTARY,
        )
        and payload.minutes <= 0
    ):
        raise ValidationAppError(f"{payload.type.value} must add a positive number of minutes.")
    if payload.type == CreditTransactionType.REFUND and payload.minutes >= 0:
        raise ValidationAppError("A refund must remove minutes (negative amount).")

    transaction = await service.grant(
        organization_id,
        type=payload.type,
        minutes=payload.minutes,
        reason=payload.reason,
        reference=payload.reference,
        created_by_user_id=auth.user.id,
    )

    await AuditService(AuditRepository(db)).record(
        organization_id=organization_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="voice_credits.admin_adjustment",
        resource_type="voice_credit_transaction",
        resource_id=transaction.id,
    )

    return _to_transaction_response(transaction)


@router.get(
    "/organizations/{organization_id}/recharge-orders",
    response_model=list[RechargeOrderResponse],
)
async def list_organization_recharge_orders(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[RechargeOrderResponse]:
    await _require_organization(organization_id, db)
    orders = await RechargeOrderRepository(db).list_for_organization(organization_id)
    return [_to_order_response(o) for o in orders]


@router.get("/recharge-packages", response_model=list[RechargePackageResponse])
async def list_all_recharge_packages(
    db: AsyncSession = Depends(get_db),
) -> list[RechargePackageResponse]:
    packages = await RechargePackageRepository(db).list_all()
    return [_to_package_response(p) for p in packages]


@router.post("/recharge-packages", response_model=RechargePackageResponse, status_code=201)
async def create_recharge_package(
    payload: CreateRechargePackageRequest,
    db: AsyncSession = Depends(get_db),
) -> RechargePackageResponse:
    package = RechargePackage(
        label=payload.label,
        minutes=payload.minutes,
        amount=payload.amount,
        currency=payload.currency.upper(),
        display_order=payload.display_order,
    )
    package = await RechargePackageRepository(db).add(package)
    return _to_package_response(package)


@router.patch("/recharge-packages/{package_id}", response_model=RechargePackageResponse)
async def update_recharge_package(
    package_id: str,
    payload: UpdateRechargePackageRequest,
    db: AsyncSession = Depends(get_db),
) -> RechargePackageResponse:
    repo = RechargePackageRepository(db)
    package = await repo.get_by_id(package_id)
    if package is None:
        raise NotFoundError("Recharge package not found.")

    if payload.label is not None:
        package.label = payload.label
    if payload.minutes is not None:
        package.minutes = payload.minutes
    if payload.amount is not None:
        package.amount = payload.amount
    if payload.currency is not None:
        package.currency = payload.currency.upper()
    if payload.is_active is not None:
        package.is_active = payload.is_active
    if payload.display_order is not None:
        package.display_order = payload.display_order

    return _to_package_response(package)
