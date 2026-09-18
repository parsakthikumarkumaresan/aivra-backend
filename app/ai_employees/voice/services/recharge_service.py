from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.models.credit_transaction import CreditTransactionType
from app.ai_employees.voice.models.recharge_order import RechargeOrder, RechargeOrderStatus
from app.ai_employees.voice.models.recharge_package import RechargePackage
from app.ai_employees.voice.repositories.recharge_repository import (
    RechargeOrderRepository,
    RechargePackageRepository,
)
from app.ai_employees.voice.services.credit_ledger_service import CreditLedgerService
from app.billing.providers.base import PaymentProvider
from app.billing.repositories.payment_event_repository import PaymentEventRepository
from app.core.config import get_settings
from app.shared.errors.exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

_RECHARGE_PURPOSE = "jaan_voice_recharge"


class RechargeService:
    """Jaan Voice Credit recharge purchases (Phase 4 spec sections 2-4).

    Deliberately owns its OWN Stripe webhook endpoint/secret
    (``/internal/voice/webhooks/stripe-recharge``), separate from the
    platform subscription webhook in app.subscriptions — see
    app.core.config's voice_recharge_stripe_webhook_secret docstring. This
    keeps Jaan Voice billing fully independent of HR/subscription billing
    code paths, per the product boundary instruction.
    """

    def __init__(
        self,
        session: AsyncSession,
        package_repo: RechargePackageRepository,
        order_repo: RechargeOrderRepository,
        payment_event_repo: PaymentEventRepository,
        ledger_service: CreditLedgerService,
        payment_provider: PaymentProvider,
    ) -> None:
        self.session = session
        self.package_repo = package_repo
        self.order_repo = order_repo
        self.payment_event_repo = payment_event_repo
        self.ledger_service = ledger_service
        self.payment_provider = payment_provider

    async def list_active_packages(self) -> list[RechargePackage]:
        return await self.package_repo.list_active()

    async def list_orders(self, organization_id: str) -> list[RechargeOrder]:
        return await self.order_repo.list_for_organization(organization_id)

    async def get_order(self, organization_id: str, order_id: str) -> RechargeOrder:
        order = await self.order_repo.get_by_id(organization_id, order_id)
        if order is None:
            raise NotFoundError("Recharge order not found.")
        return order

    async def create_recharge_order(
        self,
        organization_id: str,
        *,
        package_id: str,
        customer_email: str,
        created_by_user_id: str,
    ) -> tuple[RechargeOrder, str]:
        package = await self.package_repo.get_by_id(package_id)
        if package is None or not package.is_active:
            raise NotFoundError("Recharge package not found or is no longer available.")

        settings = get_settings()

        # Snapshot the package's current price/minutes onto the order (see
        # RechargeOrder docstring) so a later package edit never rewrites a
        # past order's financial record.
        order = RechargeOrder(
            organization_id=organization_id,
            package_id=package.id,
            minutes=package.minutes,
            amount=package.amount,
            currency=package.currency,
            status=RechargeOrderStatus.PENDING,
            created_by_user_id=created_by_user_id,
        )
        order = await self.order_repo.add(order)

        checkout = await self.payment_provider.create_payment_checkout_session(
            organization_id=organization_id,
            customer_email=customer_email,
            amount=Decimal(str(package.amount)),
            currency=package.currency,
            description=f"Jaan Voice Credits — {package.label} ({package.minutes} minutes)",
            metadata={
                "purpose": _RECHARGE_PURPOSE,
                "recharge_order_id": order.id,
                "organization_id": organization_id,
            },
            success_url=settings.voice_recharge_success_url,
            cancel_url=settings.voice_recharge_cancel_url,
            idempotency_key=f"voice-recharge-checkout:{order.id}",
        )
        order.provider_checkout_session_id = checkout.provider_session_id
        return order, checkout.checkout_url

    async def handle_stripe_webhook(self, *, payload: bytes, signature_header: str) -> None:
        settings = get_settings()
        event = self.payment_provider.verify_webhook_signature(
            payload=payload,
            signature_header=signature_header,
            webhook_secret=settings.voice_recharge_stripe_webhook_secret.get_secret_value(),
        )

        data_object = event.data.get("data", {}).get("object", {})
        organization_id = (
            data_object.get("client_reference_id")
            or data_object.get("metadata", {}).get("organization_id")
            or "unknown"
        )

        # Idempotency layer 1: the same Stripe event delivered twice (retry
        # after a timeout, or a duplicate concurrent delivery) must never be
        # applied twice. Insert-first inside a SAVEPOINT and let the DB's
        # unique constraint on provider_event_id be the actual race-proof
        # gate — a plain "check then insert" has a race window under truly
        # concurrent delivery that this closes.
        try:
            async with self.session.begin_nested():
                await self.payment_event_repo.record(
                    organization_id=organization_id,
                    provider="stripe",
                    provider_event_id=event.provider_event_id,
                    event_type=event.event_type,
                    payload=json.dumps(event.data),
                )
        except IntegrityError:
            logger.info(
                "voice_recharge_webhook_duplicate_event",
                extra={"event_id": event.provider_event_id},
            )
            return

        if event.event_type != "checkout.session.completed":
            return

        if data_object.get("metadata", {}).get("purpose") != _RECHARGE_PURPOSE:
            return  # a subscription checkout event, not ours — ignore

        checkout_session_id = data_object.get("id")
        if not checkout_session_id:
            return

        # Idempotency layer 2: even if the same *logical* payment somehow
        # produced two different Stripe event ids (not something Stripe
        # does today, but defense-in-depth per spec section 13), the
        # order's own status is re-checked under a row lock before ever
        # crediting the ledger.
        order = await self.order_repo.get_by_checkout_session_id_for_update(checkout_session_id)
        if order is None:
            logger.warning(
                "voice_recharge_webhook_unknown_order",
                extra={"checkout_session_id": checkout_session_id},
            )
            return
        if order.status == RechargeOrderStatus.PAID:
            return  # already applied

        payment_reference = data_object.get("payment_intent") or checkout_session_id
        order.status = RechargeOrderStatus.PAID
        order.paid_at = datetime.now(UTC)
        order.provider_payment_reference = payment_reference

        await self.ledger_service.grant(
            order.organization_id,
            type=CreditTransactionType.RECHARGE,
            minutes=order.minutes,
            amount=float(order.amount),
            currency=order.currency,
            reference=payment_reference,
            reason="Jaan Voice Credit recharge",
            recharge_order_id=order.id,
        )

    async def cancel_pending_order(self, organization_id: str, order_id: str) -> RechargeOrder:
        order = await self.get_order(organization_id, order_id)
        if order.status != RechargeOrderStatus.PENDING:
            raise ConflictError("Only a pending recharge order can be cancelled.")
        order.status = RechargeOrderStatus.CANCELLED
        return order
