"""Selects the configured ``PaymentProvider`` implementation.

Call sites depend on this factory and the ``PaymentProvider`` interface —
never on ``StripePaymentProvider`` directly — so swapping providers later
(ADR 0001) does not touch subscription/billing service code.
"""

from __future__ import annotations

from app.billing.providers.base import PaymentProvider
from app.billing.providers.stripe_provider import StripePaymentProvider
from app.core.config import get_settings


def get_payment_provider() -> PaymentProvider:
    provider = get_settings().payment_provider
    if provider == "stripe":
        return StripePaymentProvider()
    raise ValueError(f"Unsupported payment provider configured: {provider!r}")
