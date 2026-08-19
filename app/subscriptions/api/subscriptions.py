from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.billing.providers.base import PaymentProvider
from app.billing.providers.factory import get_payment_provider
from app.billing.repositories.invoice_repository import InvoiceRepository
from app.billing.repositories.payment_event_repository import PaymentEventRepository
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import ORG_MANAGEMENT_ROLES
from app.shared.security.dependencies import AuthContext, require_organization_context, require_role
from app.subscriptions.models.plan import BillingCycle
from app.subscriptions.models.subscription import Subscription
from app.subscriptions.repositories.plan_repository import PlanRepository
from app.subscriptions.repositories.subscription_repository import SubscriptionRepository
from app.subscriptions.schemas.subscription import (
    BillingPortalResponse,
    ChangeBillingCycleRequest,
    CheckoutResponse,
    HireEmployeeRequest,
    InvoiceResponse,
    PlanResponse,
    SubscriptionResponse,
)
from app.subscriptions.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])


def _service(
    db: AsyncSession = Depends(get_db),
    payment_provider: PaymentProvider = Depends(get_payment_provider),
) -> SubscriptionService:
    return SubscriptionService(
        SubscriptionRepository(db),
        PlanRepository(db),
        InvoiceRepository(db),
        PaymentEventRepository(db),
        CatalogRepository(db),
        ProvisioningService(ProvisionRepository(db)),
        payment_provider,
    )


def _catalog_repo(db: AsyncSession = Depends(get_db)) -> CatalogRepository:
    return CatalogRepository(db)


async def _resolve_employee_type_id(employee_type: str, catalog_repo: CatalogRepository) -> str:
    employee_type_row = await catalog_repo.get_employee_type_by_code(employee_type)
    if employee_type_row is None:
        raise NotFoundError("Unknown AI Employee type.")
    return employee_type_row.id


def _to_response(subscription: Subscription, employee_type_code: str) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=subscription.id,
        employee_type=employee_type_code,
        status=subscription.status,
        billing_cycle=subscription.billing_cycle,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    auth: AuthContext = Depends(require_organization_context),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> list[SubscriptionResponse]:
    subscriptions = await service.list_for_organization(auth.require_organization_id())
    responses = []
    for subscription in subscriptions:
        employee_type_row = await catalog_repo.get_employee_type(subscription.employee_type_id)
        code = employee_type_row.code if employee_type_row else subscription.employee_type_id
        responses.append(_to_response(subscription, code))
    return responses


@router.get("/{employee_type}", response_model=SubscriptionResponse)
async def get_subscription(
    employee_type: str,
    auth: AuthContext = Depends(require_organization_context),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> SubscriptionResponse:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    subscription = await service.get_for_employee_type(
        auth.require_organization_id(), employee_type_id
    )
    if subscription is None:
        raise NotFoundError("No subscription exists for this AI Employee yet.")
    return _to_response(subscription, employee_type)


@router.post("/{employee_type}/checkout", response_model=CheckoutResponse, status_code=201)
async def hire_employee(
    employee_type: str,
    payload: HireEmployeeRequest,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> CheckoutResponse:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    subscription, checkout_url = await service.hire(
        organization_id=auth.require_organization_id(),
        employee_type_id=employee_type_id,
        billing_cycle=BillingCycle(payload.billing_cycle),
        customer_email=auth.user.email,
    )
    return CheckoutResponse(
        subscription=_to_response(subscription, employee_type), checkout_url=checkout_url
    )


@router.post("/{employee_type}/pause", response_model=SubscriptionResponse)
async def pause_subscription(
    employee_type: str,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> SubscriptionResponse:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    subscription = await service.pause(
        organization_id=auth.require_organization_id(), employee_type_id=employee_type_id
    )
    return _to_response(subscription, employee_type)


@router.post("/{employee_type}/resume", response_model=SubscriptionResponse)
async def resume_subscription(
    employee_type: str,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> SubscriptionResponse:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    subscription = await service.resume(
        organization_id=auth.require_organization_id(), employee_type_id=employee_type_id
    )
    return _to_response(subscription, employee_type)


@router.post("/{employee_type}/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    employee_type: str,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> SubscriptionResponse:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    subscription = await service.cancel(
        organization_id=auth.require_organization_id(), employee_type_id=employee_type_id
    )
    return _to_response(subscription, employee_type)


@router.patch("/{employee_type}/billing-cycle", response_model=SubscriptionResponse)
async def change_billing_cycle(
    employee_type: str,
    payload: ChangeBillingCycleRequest,
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
) -> SubscriptionResponse:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    subscription = await service.change_billing_cycle(
        organization_id=auth.require_organization_id(),
        employee_type_id=employee_type_id,
        billing_cycle=BillingCycle(payload.billing_cycle),
    )
    return _to_response(subscription, employee_type)


@billing_router.get("/plans/{employee_type}", response_model=list[PlanResponse])
async def list_plans(
    employee_type: str,
    _auth: AuthContext = Depends(require_organization_context),
    catalog_repo: CatalogRepository = Depends(_catalog_repo),
    db: AsyncSession = Depends(get_db),
) -> list[PlanResponse]:
    employee_type_id = await _resolve_employee_type_id(employee_type, catalog_repo)
    plans = await PlanRepository(db).list_for_employee_type(employee_type_id)
    return [
        PlanResponse(
            id=plan.id,
            employee_type=employee_type,
            code=plan.code,
            name=plan.name,
            billing_cycle=plan.billing_cycle,
            price=float(plan.price),
            currency=plan.currency,
        )
        for plan in plans
    ]


@billing_router.post("/webhooks/stripe", status_code=200, response_model=None)
async def stripe_webhook(
    request: Request, response: Response, service: SubscriptionService = Depends(_service)
) -> dict:
    """No auth dependency — Stripe signs the payload itself (verified inside
    the service via ``PaymentProvider.verify_webhook_signature``), and the
    caller is Stripe's infrastructure, not an authenticated AIVRA user.
    """
    payload = await request.body()
    signature_header = request.headers.get("Stripe-Signature", "")
    await service.handle_webhook_event(payload=payload, signature_header=signature_header)
    return {"received": True}


@billing_router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
) -> list[InvoiceResponse]:
    invoices = await service.list_invoices(auth.require_organization_id())
    return [InvoiceResponse.model_validate(invoice) for invoice in invoices]


@billing_router.get("/portal", response_model=BillingPortalResponse)
async def get_billing_portal(
    auth: AuthContext = Depends(require_role(*ORG_MANAGEMENT_ROLES)),
    service: SubscriptionService = Depends(_service),
) -> BillingPortalResponse:
    portal_url = await service.get_billing_portal_url(auth.require_organization_id())
    return BillingPortalResponse(portal_url=portal_url)
