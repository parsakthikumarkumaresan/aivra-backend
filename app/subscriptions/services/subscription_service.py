"""HR subscription lifecycle (spec sections 17, 23.1/43.1).

Activation is webhook-driven, not client-triggered: ``hire`` only creates a
PENDING_ACTIVATION row and a Stripe Checkout session — the transition to
ACTIVE happens exclusively in ``handle_webhook_event`` once Stripe confirms
payment. This differs from the frontend prototype's mock
``completeActivation``, which flipped status directly on a client call; a
client-triggered activation endpoint would let anyone mark themselves ACTIVE
without paying, so the real backend does not offer one (spec section 1.1:
"the backend is the source of truth for ... subscription access"). The
frontend's `completeActivation` call now maps to `get_subscription` (poll
current status while the webhook lands) — see app/subscriptions/api/subscriptions.py.

Every mutation here also mirrors the transition into the shared
``EmployeeProvision`` row via ``ProvisioningService`` — that is what actually
gates HR feature access (spec section 8), not the Subscription row itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.ai_employees.provisioning.models.provision import ProvisionStatus
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.billing.models.invoice import Invoice, InvoiceStatus
from app.billing.providers.base import PaymentProvider
from app.billing.repositories.invoice_repository import InvoiceRepository
from app.billing.repositories.payment_event_repository import PaymentEventRepository
from app.shared.errors.exceptions import ConflictError, NotFoundError
from app.subscriptions.models.plan import BillingCycle
from app.subscriptions.models.subscription import (
    SUBSCRIPTION_TRANSITIONS,
    Subscription,
    SubscriptionStatus,
)
from app.subscriptions.repositories.plan_repository import PlanRepository
from app.subscriptions.repositories.subscription_repository import SubscriptionRepository

_STATUS_TO_PROVISION_STATUS = {
    SubscriptionStatus.PENDING_ACTIVATION: ProvisionStatus.PENDING_ACTIVATION,
    SubscriptionStatus.ACTIVE: ProvisionStatus.ACTIVE,
    SubscriptionStatus.PAUSED: ProvisionStatus.PAUSED,
    SubscriptionStatus.PAST_DUE: ProvisionStatus.PAST_DUE,
    SubscriptionStatus.CANCELLED: ProvisionStatus.CANCELLED,
    SubscriptionStatus.EXPIRED: ProvisionStatus.EXPIRED,
}


class SubscriptionService:
    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        plan_repo: PlanRepository,
        invoice_repo: InvoiceRepository,
        payment_event_repo: PaymentEventRepository,
        catalog_repo: CatalogRepository,
        provisioning: ProvisioningService,
        payment_provider: PaymentProvider,
    ) -> None:
        self.subscription_repo = subscription_repo
        self.plan_repo = plan_repo
        self.invoice_repo = invoice_repo
        self.payment_event_repo = payment_event_repo
        self.catalog_repo = catalog_repo
        self.provisioning = provisioning
        self.payment_provider = payment_provider

    async def list_for_organization(self, organization_id: str) -> list[Subscription]:
        return await self.subscription_repo.list_for_organization(organization_id)

    async def get_for_employee_type(
        self, organization_id: str, employee_type_id: str
    ) -> Subscription | None:
        return await self.subscription_repo.get_for_employee_type(organization_id, employee_type_id)

    async def _get_or_create(self, organization_id: str, employee_type_id: str) -> Subscription:
        existing = await self.subscription_repo.get_for_employee_type(
            organization_id, employee_type_id
        )
        if existing is not None:
            return existing
        plan = await self.plan_repo.get_default_for_employee_type_and_cycle(
            employee_type_id, BillingCycle.MONTHLY
        )
        if plan is None:
            raise NotFoundError("No plan is configured for this AI Employee yet.")
        subscription = Subscription(
            organization_id=organization_id,
            employee_type_id=employee_type_id,
            plan_id=plan.id,
            status=SubscriptionStatus.NOT_HIRED,
            billing_cycle=plan.billing_cycle,
        )
        return await self.subscription_repo.add(subscription)

    async def hire(
        self,
        *,
        organization_id: str,
        employee_type_id: str,
        billing_cycle: BillingCycle,
        customer_email: str,
    ) -> tuple[Subscription, str]:
        subscription = await self._get_or_create(organization_id, employee_type_id)
        if subscription.status not in (SubscriptionStatus.NOT_HIRED, SubscriptionStatus.EXPIRED):
            raise ConflictError("This AI Employee already has an active or pending subscription.")

        plan = await self.plan_repo.get_default_for_employee_type_and_cycle(
            employee_type_id, billing_cycle
        )
        if plan is None or plan.external_price_id is None:
            raise NotFoundError("No purchasable plan is configured for this billing cycle.")

        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            subscription.status, SubscriptionStatus.PENDING_ACTIVATION
        )
        subscription.status = SubscriptionStatus.PENDING_ACTIVATION
        subscription.plan_id = plan.id
        subscription.billing_cycle = billing_cycle

        checkout = await self.payment_provider.create_checkout_session(
            organization_id=organization_id,
            customer_email=customer_email,
            plan_external_price_id=plan.external_price_id,
            provider_customer_id=subscription.provider_customer_id,
            idempotency_key=f"checkout:{subscription.id}:{plan.id}",
        )

        await self.provisioning.transition(
            organization_id=organization_id,
            employee_type_id=employee_type_id,
            target_status=ProvisionStatus.PENDING_ACTIVATION,
            reason="HR subscription checkout started",
            actor_id=None,
            actor_type="SYSTEM",
        )
        return subscription, checkout.checkout_url

    async def pause(self, *, organization_id: str, employee_type_id: str) -> Subscription:
        subscription = await self._require_existing(organization_id, employee_type_id)
        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            subscription.status, SubscriptionStatus.PAUSED
        )
        if subscription.provider_subscription_id:
            await self.payment_provider.pause_subscription(
                provider_subscription_id=subscription.provider_subscription_id
            )
        subscription.status = SubscriptionStatus.PAUSED
        await self._mirror_provision(organization_id, employee_type_id, SubscriptionStatus.PAUSED)
        return subscription

    async def resume(self, *, organization_id: str, employee_type_id: str) -> Subscription:
        subscription = await self._require_existing(organization_id, employee_type_id)
        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            subscription.status, SubscriptionStatus.ACTIVE
        )
        if subscription.provider_subscription_id:
            await self.payment_provider.resume_subscription(
                provider_subscription_id=subscription.provider_subscription_id
            )
        subscription.status = SubscriptionStatus.ACTIVE
        await self._mirror_provision(organization_id, employee_type_id, SubscriptionStatus.ACTIVE)
        return subscription

    async def cancel(self, *, organization_id: str, employee_type_id: str) -> Subscription:
        subscription = await self._require_existing(organization_id, employee_type_id)
        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            subscription.status, SubscriptionStatus.CANCELLED
        )
        if subscription.provider_subscription_id:
            await self.payment_provider.cancel_subscription(
                provider_subscription_id=subscription.provider_subscription_id
            )
        subscription.status = SubscriptionStatus.CANCELLED
        await self._mirror_provision(
            organization_id, employee_type_id, SubscriptionStatus.CANCELLED
        )
        return subscription

    async def change_billing_cycle(
        self, *, organization_id: str, employee_type_id: str, billing_cycle: BillingCycle
    ) -> Subscription:
        """MVP decision: takes effect immediately, no proration credit — the
        next Stripe invoice reflects the new plan. Proration is deferred
        (spec section 41 MVP discipline).
        """
        subscription = await self._require_existing(organization_id, employee_type_id)
        plan = await self.plan_repo.get_default_for_employee_type_and_cycle(
            employee_type_id, billing_cycle
        )
        if plan is None:
            raise NotFoundError("No plan is configured for this billing cycle.")
        subscription.plan_id = plan.id
        subscription.billing_cycle = billing_cycle
        return subscription

    async def get_billing_portal_url(self, organization_id: str) -> str:
        subscriptions = await self.subscription_repo.list_for_organization(organization_id)
        customer_id = next(
            (s.provider_customer_id for s in subscriptions if s.provider_customer_id), None
        )
        if customer_id is None:
            raise NotFoundError("No billing account exists for this organization yet.")
        session = await self.payment_provider.create_billing_portal_session(
            provider_customer_id=customer_id
        )
        return session.portal_url

    async def list_invoices(self, organization_id: str) -> list[Invoice]:
        return await self.invoice_repo.list_for_organization(organization_id)

    async def handle_webhook_event(self, *, payload: bytes, signature_header: str) -> None:
        event = self.payment_provider.verify_webhook_signature(
            payload=payload, signature_header=signature_header
        )

        existing = await self.payment_event_repo.get_by_provider_event_id(event.provider_event_id)
        if existing is not None:
            return  # already processed — webhook idempotency (spec sections 28, 39)

        data_object = event.data.get("data", {}).get("object", {})

        if event.event_type == "checkout.session.completed":
            await self._handle_checkout_completed(data_object)
        elif event.event_type == "invoice.paid":
            await self._handle_invoice_paid(data_object)
        elif event.event_type == "invoice.payment_failed":
            await self._handle_invoice_payment_failed(data_object)
        elif event.event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(data_object)

        organization_id = self._organization_id_from_event(data_object)
        await self.payment_event_repo.record(
            organization_id=organization_id or "unknown",
            provider="stripe",
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            payload=json.dumps(event.data),
        )

    @staticmethod
    def _organization_id_from_event(data_object: dict) -> str | None:
        return (
            data_object.get("client_reference_id")
            or data_object.get("metadata", {}).get("organization_id")
        )

    async def _handle_checkout_completed(self, data_object: dict) -> None:
        organization_id = self._organization_id_from_event(data_object)
        if organization_id is None:
            return
        provider_subscription_id = data_object.get("subscription")
        provider_customer_id = data_object.get("customer")

        subscriptions = await self.subscription_repo.list_for_organization(organization_id)
        pending = next(
            (s for s in subscriptions if s.status == SubscriptionStatus.PENDING_ACTIVATION), None
        )
        if pending is None:
            return

        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            pending.status, SubscriptionStatus.ACTIVE
        )
        pending.status = SubscriptionStatus.ACTIVE
        pending.provider_subscription_id = provider_subscription_id
        pending.provider_customer_id = provider_customer_id
        pending.current_period_end = datetime.now(UTC) + timedelta(days=30)
        await self._mirror_provision(
            organization_id, pending.employee_type_id, SubscriptionStatus.ACTIVE
        )

    async def _handle_invoice_paid(self, data_object: dict) -> None:
        provider_subscription_id = data_object.get("subscription")
        if provider_subscription_id is None:
            return
        subscription = await self.subscription_repo.get_by_provider_subscription_id(
            provider_subscription_id
        )
        if subscription is None:
            return

        invoice = Invoice(
            organization_id=subscription.organization_id,
            subscription_id=subscription.id,
            status=InvoiceStatus.PAID,
            amount=data_object.get("amount_paid", 0) / 100,
            currency=data_object.get("currency", "usd").upper(),
            period_start=datetime.fromtimestamp(data_object["period_start"], tz=UTC),
            period_end=datetime.fromtimestamp(data_object["period_end"], tz=UTC),
            issued_at=datetime.now(UTC),
            paid_at=datetime.now(UTC),
            provider_invoice_id=data_object.get("id"),
            hosted_invoice_url=data_object.get("hosted_invoice_url"),
        )
        self.invoice_repo.session.add(invoice)
        await self.invoice_repo.session.flush()

        if subscription.status == SubscriptionStatus.PAST_DUE:
            SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
                subscription.status, SubscriptionStatus.ACTIVE
            )
            subscription.status = SubscriptionStatus.ACTIVE
            await self._mirror_provision(
                subscription.organization_id,
                subscription.employee_type_id,
                SubscriptionStatus.ACTIVE,
            )
        subscription.current_period_end = datetime.fromtimestamp(
            data_object["period_end"], tz=UTC
        )

    async def _handle_invoice_payment_failed(self, data_object: dict) -> None:
        provider_subscription_id = data_object.get("subscription")
        if provider_subscription_id is None:
            return
        subscription = await self.subscription_repo.get_by_provider_subscription_id(
            provider_subscription_id
        )
        if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
            return
        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            subscription.status, SubscriptionStatus.PAST_DUE
        )
        subscription.status = SubscriptionStatus.PAST_DUE
        await self._mirror_provision(
            subscription.organization_id, subscription.employee_type_id, SubscriptionStatus.PAST_DUE
        )

    async def _handle_subscription_deleted(self, data_object: dict) -> None:
        provider_subscription_id = data_object.get("id")
        if provider_subscription_id is None:
            return
        subscription = await self.subscription_repo.get_by_provider_subscription_id(
            provider_subscription_id
        )
        if subscription is None or subscription.status == SubscriptionStatus.CANCELLED:
            return
        SUBSCRIPTION_TRANSITIONS.assert_transition_allowed(
            subscription.status, SubscriptionStatus.CANCELLED
        )
        subscription.status = SubscriptionStatus.CANCELLED
        await self._mirror_provision(
            subscription.organization_id,
            subscription.employee_type_id,
            SubscriptionStatus.CANCELLED,
        )

    async def _require_existing(self, organization_id: str, employee_type_id: str) -> Subscription:
        subscription = await self.subscription_repo.get_for_employee_type(
            organization_id, employee_type_id
        )
        if subscription is None:
            raise NotFoundError("No subscription exists for this AI Employee.")
        return subscription

    async def _mirror_provision(
        self, organization_id: str, employee_type_id: str, status: SubscriptionStatus
    ) -> None:
        await self.provisioning.transition(
            organization_id=organization_id,
            employee_type_id=employee_type_id,
            target_status=_STATUS_TO_PROVISION_STATUS[status],
            reason=f"Subscription transitioned to {status.value}",
            actor_id=None,
            actor_type="SYSTEM",
        )
