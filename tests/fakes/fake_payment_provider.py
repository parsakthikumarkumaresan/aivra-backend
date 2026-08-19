"""In-memory ``PaymentProvider`` for tests — no network calls, deterministic
IDs, and a helper to synthesize a signed-looking webhook payload without
needing a real Stripe webhook secret handshake.
"""

from __future__ import annotations

import itertools
import json

from app.billing.providers.base import CheckoutSession, PaymentProvider, PortalSession, WebhookEvent


class FakePaymentProvider(PaymentProvider):
    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self.cancelled_subscription_ids: list[str] = []
        self.paused_subscription_ids: list[str] = []
        self.resumed_subscription_ids: list[str] = []

    async def create_checkout_session(
        self,
        *,
        organization_id: str,
        customer_email: str,
        plan_external_price_id: str,
        provider_customer_id: str | None,
        idempotency_key: str,
    ) -> CheckoutSession:
        session_id = f"cs_test_{next(self._counter)}"
        return CheckoutSession(
            checkout_url=f"https://checkout.example.test/{session_id}",
            provider_session_id=session_id,
        )

    async def create_billing_portal_session(self, *, provider_customer_id: str) -> PortalSession:
        return PortalSession(portal_url=f"https://billing.example.test/{provider_customer_id}")

    async def pause_subscription(self, *, provider_subscription_id: str) -> None:
        self.paused_subscription_ids.append(provider_subscription_id)

    async def resume_subscription(self, *, provider_subscription_id: str) -> None:
        self.resumed_subscription_ids.append(provider_subscription_id)

    async def cancel_subscription(self, *, provider_subscription_id: str) -> None:
        self.cancelled_subscription_ids.append(provider_subscription_id)

    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> WebhookEvent:
        # Tests build the event body directly and pass a sentinel header —
        # real signature HMAC verification is covered by
        # tests/unit/test_stripe_provider.py against StripePaymentProvider.
        if signature_header != "fake-signature":
            from app.shared.errors.exceptions import WebhookSignatureInvalidError

            raise WebhookSignatureInvalidError("Invalid test signature sentinel.")
        data = json.loads(payload)
        return WebhookEvent(
            provider_event_id=data["id"],
            event_type=data["type"],
            raw_payload=payload.decode("utf-8"),
            data=data,
        )

    @staticmethod
    def build_event(event_id: str, event_type: str, data_object: dict) -> bytes:
        body = {"id": event_id, "type": event_type, "data": {"object": data_object}}
        return json.dumps(body).encode()
