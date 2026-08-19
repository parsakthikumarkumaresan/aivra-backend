"""HR subscription lifecycle end-to-end: checkout -> webhook activation ->
webhook idempotency (mandatory, spec section 39) -> pause/resume/cancel ->
provisioning entitlement mirrors every transition.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.registry.models.catalog import (
    AIEmployeeType,
    CommercialModel,
    EmployeeCatalogItem,
    EmployeeTypeCode,
)
from app.billing.providers.factory import get_payment_provider
from app.subscriptions.models.plan import BillingCycle, Plan
from tests.fakes.fake_payment_provider import FakePaymentProvider


async def _seed_hr_catalog(db_session: AsyncSession) -> tuple[AIEmployeeType, Plan]:
    hr_type = AIEmployeeType(
        code=EmployeeTypeCode.HR,
        name="AI HR Employee",
        description="Recruiting automation",
        commercial_model=CommercialModel.SELF_SERVICE_SUBSCRIPTION,
    )
    db_session.add(hr_type)
    await db_session.flush()

    db_session.add(
        EmployeeCatalogItem(
            employee_type_id=hr_type.id,
            name="AI HR Employee",
            tagline="Hire smarter",
            description="Full pipeline automation",
            base_price_monthly=99.00,
        )
    )
    plan = Plan(
        employee_type_id=hr_type.id,
        code="hr_standard_monthly_test",
        name="HR Standard",
        billing_cycle=BillingCycle.MONTHLY,
        price=99.00,
        external_price_id="price_test_hr_standard",
    )
    db_session.add(plan)
    await db_session.flush()
    return hr_type, plan


async def _register_login_and_select_org(client: AsyncClient, email: str, slug: str) -> dict:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123!", "fullName": "Owner"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SuperSecret123!"}
    )
    token = login.json()["accessToken"]
    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": slug, "slug": slug},
        headers={"Authorization": f"Bearer {token}"},
    )
    org_id = org_resp.json()["id"]
    csrf = client.cookies.get("aivra_csrf")
    select_resp = await client.post(
        "/api/v1/auth/select-organization",
        json={"organizationId": org_id},
        headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf},
    )
    return {"token": select_resp.json()["accessToken"], "org_id": org_id}


async def test_full_subscription_lifecycle(
    app, client: AsyncClient, db_session: AsyncSession
) -> None:
    fake_provider = FakePaymentProvider()
    app.dependency_overrides[get_payment_provider] = lambda: fake_provider

    await _seed_hr_catalog(db_session)
    session = await _register_login_and_select_org(client, "sub-owner@example.com", "sub-org")
    auth_headers = {"Authorization": f"Bearer {session['token']}"}

    # 1. Hire -> PENDING_ACTIVATION + checkout URL from the (fake) provider.
    checkout_resp = await client.post(
        "/api/v1/subscriptions/hr/checkout", json={"billingCycle": "monthly"}, headers=auth_headers
    )
    assert checkout_resp.status_code == 201, checkout_resp.text
    checkout_body = checkout_resp.json()
    assert checkout_body["subscription"]["status"] == "pending_activation"
    assert checkout_body["checkoutUrl"].startswith("https://checkout.example.test/")

    employee_resp = await client.get("/api/v1/employees", headers=auth_headers)
    hr_employee = next(e for e in employee_resp.json() if e["type"] == "hr")
    assert hr_employee["status"] == "pending_activation"

    # 2. Simulate the Stripe checkout.session.completed webhook.
    event_payload = FakePaymentProvider.build_event(
        "evt_test_1",
        "checkout.session.completed",
        {
            "client_reference_id": session["org_id"],
            "subscription": "sub_test_123",
            "customer": "cus_test_123",
        },
    )
    webhook_resp = await client.post(
        "/api/v1/billing/webhooks/stripe",
        content=event_payload,
        headers={"Stripe-Signature": "fake-signature"},
    )
    assert webhook_resp.status_code == 200

    sub_resp = await client.get("/api/v1/subscriptions/hr", headers=auth_headers)
    assert sub_resp.json()["status"] == "active"

    employee_resp = await client.get("/api/v1/employees", headers=auth_headers)
    hr_employee = next(e for e in employee_resp.json() if e["type"] == "hr")
    assert hr_employee["status"] == "active"

    # 3. Replaying the identical webhook event must be a no-op (mandatory
    # duplicate-webhook idempotency test, spec sections 28/39).
    replay_resp = await client.post(
        "/api/v1/billing/webhooks/stripe",
        content=event_payload,
        headers={"Stripe-Signature": "fake-signature"},
    )
    assert replay_resp.status_code == 200
    sub_resp_after_replay = await client.get("/api/v1/subscriptions/hr", headers=auth_headers)
    assert sub_resp_after_replay.json()["status"] == "active"

    # 4. Pause -> provider called, status mirrors to provisioning.
    pause_resp = await client.post("/api/v1/subscriptions/hr/pause", headers=auth_headers)
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"
    assert "sub_test_123" in fake_provider.paused_subscription_ids

    employee_resp = await client.get("/api/v1/employees", headers=auth_headers)
    hr_employee = next(e for e in employee_resp.json() if e["type"] == "hr")
    assert hr_employee["status"] == "paused"

    # 5. Resume -> back to active.
    resume_resp = await client.post("/api/v1/subscriptions/hr/resume", headers=auth_headers)
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "active"
    assert "sub_test_123" in fake_provider.resumed_subscription_ids

    # 6. Cancel -> terminal state; provider called; provisioning mirrors CANCELLED.
    cancel_resp = await client.post("/api/v1/subscriptions/hr/cancel", headers=auth_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
    assert "sub_test_123" in fake_provider.cancelled_subscription_ids

    # 7. Cancelling an already-cancelled subscription is an idempotent no-op
    # (same-state "transitions" are allowed by design — see StateMachine —
    # so retried client calls or webhook replays don't error).
    second_cancel_resp = await client.post("/api/v1/subscriptions/hr/cancel", headers=auth_headers)
    assert second_cancel_resp.status_code == 200
    assert second_cancel_resp.json()["status"] == "cancelled"

    # 8. But CANCELLED genuinely has no *other* outgoing transition — pausing
    # a cancelled subscription is rejected.
    pause_after_cancel_resp = await client.post(
        "/api/v1/subscriptions/hr/pause", headers=auth_headers
    )
    assert pause_after_cancel_resp.status_code == 409
    assert pause_after_cancel_resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_webhook_with_invalid_signature_is_rejected(
    app, client: AsyncClient, db_session: AsyncSession
) -> None:
    fake_provider = FakePaymentProvider()
    app.dependency_overrides[get_payment_provider] = lambda: fake_provider

    event_payload = FakePaymentProvider.build_event(
        "evt_test_bad", "checkout.session.completed", {"client_reference_id": "org_doesnt_matter"}
    )
    response = await client.post(
        "/api/v1/billing/webhooks/stripe",
        content=event_payload,
        headers={"Stripe-Signature": "not-the-right-signature"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"
