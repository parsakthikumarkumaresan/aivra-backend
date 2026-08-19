"""Stripe adapter (ADR 0001). Talks to Stripe's REST API directly over
``httpx`` rather than the Stripe SDK, keeping the provider boundary explicit.

Untested against a live Stripe account (no credentials configured in this
environment) — see ADR 0001. Calls will fail cleanly with an HTTP error from
Stripe until ``STRIPE_SECRET_KEY`` is set; nothing here fabricates a
successful response (spec section 47).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from app.billing.providers.base import CheckoutSession, PaymentProvider, PortalSession, WebhookEvent
from app.core.config import get_settings
from app.shared.errors.exceptions import WebhookSignatureInvalidError

_WEBHOOK_TOLERANCE_SECONDS = 5 * 60


class StripePaymentProvider(PaymentProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    def _client(self) -> httpx.AsyncClient:
        secret_key = self.settings.stripe_secret_key.get_secret_value()
        return httpx.AsyncClient(
            base_url=self.settings.stripe_api_base_url,
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=15.0,
        )

    async def create_checkout_session(
        self,
        *,
        organization_id: str,
        customer_email: str,
        plan_external_price_id: str,
        provider_customer_id: str | None,
        idempotency_key: str,
    ) -> CheckoutSession:
        form: dict[str, str] = {
            "mode": "subscription",
            "line_items[0][price]": plan_external_price_id,
            "line_items[0][quantity]": "1",
            "success_url": self.settings.checkout_success_url,
            "cancel_url": self.settings.checkout_cancel_url,
            "client_reference_id": organization_id,
            "subscription_data[metadata][organization_id]": organization_id,
        }
        if provider_customer_id:
            form["customer"] = provider_customer_id
        else:
            form["customer_email"] = customer_email

        async with self._client() as client:
            response = await client.post(
                "/checkout/sessions",
                data=form,
                headers={"Idempotency-Key": idempotency_key},
            )
            response.raise_for_status()
            body = response.json()
        return CheckoutSession(checkout_url=body["url"], provider_session_id=body["id"])

    async def create_billing_portal_session(self, *, provider_customer_id: str) -> PortalSession:
        async with self._client() as client:
            response = await client.post(
                "/billing_portal/sessions",
                data={
                    "customer": provider_customer_id,
                    "return_url": self.settings.billing_portal_return_url,
                },
            )
            response.raise_for_status()
            body = response.json()
        return PortalSession(portal_url=body["url"])

    async def pause_subscription(self, *, provider_subscription_id: str) -> None:
        async with self._client() as client:
            response = await client.post(
                f"/subscriptions/{provider_subscription_id}",
                data={"pause_collection[behavior]": "void"},
            )
            response.raise_for_status()

    async def resume_subscription(self, *, provider_subscription_id: str) -> None:
        async with self._client() as client:
            response = await client.post(
                f"/subscriptions/{provider_subscription_id}",
                data={"pause_collection": ""},
            )
            response.raise_for_status()

    async def cancel_subscription(self, *, provider_subscription_id: str) -> None:
        async with self._client() as client:
            response = await client.delete(f"/subscriptions/{provider_subscription_id}")
            response.raise_for_status()

    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> WebhookEvent:
        parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
        timestamp = parts.get("t")
        signature = parts.get("v1")
        if timestamp is None or signature is None:
            raise WebhookSignatureInvalidError("Malformed Stripe-Signature header.")

        if abs(time.time() - int(timestamp)) > _WEBHOOK_TOLERANCE_SECONDS:
            raise WebhookSignatureInvalidError("Webhook timestamp outside tolerance window.")

        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode()
        expected_signature = hmac.new(
            self.settings.stripe_webhook_secret.get_secret_value().encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            raise WebhookSignatureInvalidError("Stripe webhook signature mismatch.")

        data = json.loads(payload)
        return WebhookEvent(
            provider_event_id=data["id"],
            event_type=data["type"],
            raw_payload=payload.decode("utf-8"),
            data=data,
        )
