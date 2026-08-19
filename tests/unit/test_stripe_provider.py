"""Real HMAC signature verification logic for the Stripe adapter — no
network calls, just the cryptographic check (spec section 23: webhook
signature verification is mandatory)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.billing.providers.stripe_provider import StripePaymentProvider
from app.core.config import get_settings
from app.shared.errors.exceptions import WebhookSignatureInvalidError

_TEST_WEBHOOK_SECRET = "whsec_test_secret_for_unit_tests"


def _sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    timestamp = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> StripePaymentProvider:
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", _TEST_WEBHOOK_SECRET)
    get_settings.cache_clear()
    yield StripePaymentProvider()
    get_settings.cache_clear()


def test_verify_webhook_signature_accepts_correctly_signed_payload(
    provider: StripePaymentProvider,
) -> None:
    payload = json.dumps(
        {"id": "evt_1", "type": "checkout.session.completed", "data": {}}
    ).encode()
    header = _sign(payload, _TEST_WEBHOOK_SECRET)

    event = provider.verify_webhook_signature(payload=payload, signature_header=header)
    assert event.provider_event_id == "evt_1"
    assert event.event_type == "checkout.session.completed"


def test_verify_webhook_signature_rejects_tampered_payload(
    provider: StripePaymentProvider,
) -> None:
    original_payload = json.dumps({"id": "evt_2", "type": "invoice.paid", "data": {}}).encode()
    header = _sign(original_payload, _TEST_WEBHOOK_SECRET)
    tampered_payload = json.dumps(
        {"id": "evt_2_hacked", "type": "invoice.paid", "data": {}}
    ).encode()

    with pytest.raises(WebhookSignatureInvalidError):
        provider.verify_webhook_signature(payload=tampered_payload, signature_header=header)


def test_verify_webhook_signature_rejects_stale_timestamp(
    provider: StripePaymentProvider,
) -> None:
    payload = json.dumps({"id": "evt_3", "type": "invoice.paid", "data": {}}).encode()
    stale_timestamp = int(time.time()) - 3600
    header = _sign(payload, _TEST_WEBHOOK_SECRET, timestamp=stale_timestamp)

    with pytest.raises(WebhookSignatureInvalidError):
        provider.verify_webhook_signature(payload=payload, signature_header=header)


def test_verify_webhook_signature_rejects_malformed_header(
    provider: StripePaymentProvider,
) -> None:
    payload = json.dumps({"id": "evt_4", "type": "invoice.paid", "data": {}}).encode()

    with pytest.raises(WebhookSignatureInvalidError):
        provider.verify_webhook_signature(payload=payload, signature_header="not-a-valid-header")
