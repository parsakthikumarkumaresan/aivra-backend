# ADR 0001: Payment provider for HR self-service subscriptions

**Status:** Accepted (MVP)

## Context

Spec section 44 requires freezing a payment provider before coding subscriptions.
The frontend and prior project state placed no constraint on this choice (see
frontend audit: no billing UI wired to a specific provider). The spec's
representative API surface (`GET /billing/portal`, invoices, checkout,
webhooks, pause/resume/cancel, past-due handling) closely matches Stripe's
Billing + Checkout + Customer Portal product, not a transaction-only gateway.

## Decision

Use **Stripe** as the sole MVP payment provider for HR's self-service
subscription flow (spec section 41: one payment provider to start).
Voice is managed/custom and does not go through self-service checkout.

Integration is a thin `PaymentProvider` interface
(`app/billing/providers/base.py`) with a `StripePaymentProvider` adapter
(`app/billing/providers/stripe_provider.py`) calling Stripe's REST API
directly over `httpx` (no SDK dependency, to keep the adapter boundary
explicit and swappable). Domain/service code depends only on the interface.

## Consequences

- No Stripe account/API keys are configured in this environment. The adapter
  is fully implemented against Stripe's documented REST contract, but is
  untested against a live account — this is a real, correctly-shaped
  integration boundary, not a mocked/fake success path (spec section 47).
  Set `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` to activate it.
- Switching providers later only requires a new `PaymentProvider`
  implementation; no changes to `app.subscriptions` domain logic.
