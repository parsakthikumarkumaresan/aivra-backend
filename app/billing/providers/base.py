"""Payment provider abstraction (spec section 21/29).

Domain and service code depends only on this interface — never on a
provider SDK or REST shape directly (spec section 19: "Provider-specific
SDKs must live behind infrastructure adapters").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckoutSession:
    checkout_url: str
    provider_session_id: str


@dataclass(frozen=True)
class PortalSession:
    portal_url: str


@dataclass(frozen=True)
class WebhookEvent:
    provider_event_id: str
    event_type: str
    raw_payload: str
    data: dict


class PaymentProvider(ABC):
    @abstractmethod
    async def create_checkout_session(
        self,
        *,
        organization_id: str,
        customer_email: str,
        plan_external_price_id: str,
        provider_customer_id: str | None,
        idempotency_key: str,
    ) -> CheckoutSession: ...

    @abstractmethod
    async def create_billing_portal_session(
        self, *, provider_customer_id: str
    ) -> PortalSession: ...

    @abstractmethod
    async def pause_subscription(self, *, provider_subscription_id: str) -> None: ...

    @abstractmethod
    async def resume_subscription(self, *, provider_subscription_id: str) -> None: ...

    @abstractmethod
    async def cancel_subscription(self, *, provider_subscription_id: str) -> None: ...

    @abstractmethod
    def verify_webhook_signature(
        self, *, payload: bytes, signature_header: str
    ) -> WebhookEvent: ...
