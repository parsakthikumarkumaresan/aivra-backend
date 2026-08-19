"""Lead intake -> AIVRA-internal Voice project lifecycle -> provisioning.

Covers: public unauthenticated submission + rate limiting, internal-role
gating (customers must never reach these routes — spec section 14), the
Voice deployment state machine, and that Voice provisioning only activates
once the project reaches ACTIVE (spec section 8: never automatic).
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.registry.models.catalog import (
    AIEmployeeType,
    CommercialModel,
    EmployeeTypeCode,
)
from app.identity.models.user import User
from app.shared.rbac.roles import PlatformRole
from app.shared.security.passwords import hash_password


async def _seed_voice_employee_type(db_session: AsyncSession) -> None:
    db_session.add(
        AIEmployeeType(
            code=EmployeeTypeCode.VOICE,
            name="AI Voice Employee",
            description="Custom voice agent",
            commercial_model=CommercialModel.MANAGED_CUSTOM,
        )
    )
    await db_session.flush()


async def _create_aivra_staff_and_login(client: AsyncClient, db_session: AsyncSession) -> str:
    staff = User(
        email="engineer@aivra.ai",
        password_hash=hash_password("SuperSecret123!"),
        full_name="AIVRA Engineer",
        platform_role=PlatformRole.AIVRA_ENGINEER,
    )
    db_session.add(staff)
    await db_session.flush()

    login = await client.post(
        "/api/v1/auth/login", json={"email": "engineer@aivra.ai", "password": "SuperSecret123!"}
    )
    assert login.status_code == 200, login.text
    return login.json()["accessToken"]


async def test_customer_role_cannot_reach_internal_voice_project_routes(
    client: AsyncClient,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "customer@example.com", "password": "SuperSecret123!", "fullName": "C"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "customer@example.com", "password": "SuperSecret123!"}
    )
    token = login.json()["accessToken"]

    response = await client.get(
        "/api/v1/internal/voice-projects", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_voice_customization_lead_to_active_provisioning(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_voice_employee_type(db_session)
    staff_token = await _create_aivra_staff_and_login(client, db_session)
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # 1. Public, unauthenticated customization request.
    submit_resp = await client.post(
        "/api/v1/leads/voice-customization",
        json={
            "contactName": "Jordan Lee",
            "contactEmail": "jordan@prospect.example.com",
            "companyName": "Prospect Co",
            "projectName": "Prospect Co Inbound Voice Agent",
        },
    )
    assert submit_resp.status_code == 201, submit_resp.text
    body = submit_resp.json()
    lead_id = body["lead"]["id"]
    project_id = body["voiceProjectId"]
    assert body["lead"]["status"] == "new"

    # 2. AIVRA converts the lead once a real customer organization exists.
    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Prospect Co", "slug": "prospect-co"},
        headers=staff_headers,
    )
    org_id = org_resp.json()["id"]

    convert_resp = await client.post(
        f"/api/v1/leads/{lead_id}/convert",
        json={"organizationId": org_id},
        headers=staff_headers,
    )
    assert convert_resp.status_code == 200
    assert convert_resp.json()["status"] == "converted"

    assign_resp = await client.post(
        f"/api/v1/internal/voice-projects/{project_id}/assign-organization",
        json={"organizationId": org_id},
        headers=staff_headers,
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["organizationId"] == org_id

    # The AIVRA staff member who created the org is also its OWNER member
    # (organization_service.create_organization) — select that org context
    # to check entitlement from the customer's point of view.
    csrf = client.cookies.get("aivra_csrf")
    select_resp = await client.post(
        "/api/v1/auth/select-organization",
        json={"organizationId": org_id},
        headers={**staff_headers, "X-CSRF-Token": csrf},
    )
    org_scoped_headers = {"Authorization": f"Bearer {select_resp.json()['accessToken']}"}

    # 3. Walk the full deployment state machine.
    for target in [
        "discovery",
        "requirements_collected",
        "configuration",
        "integration",
        "testing",
        "customer_approval",
        "deployment_pending",
    ]:
        resp = await client.post(
            f"/api/v1/internal/voice-projects/{project_id}/transition",
            json={"targetStatus": target},
            headers=staff_headers,
        )
        assert resp.status_code == 200, f"{target}: {resp.text}"
        assert resp.json()["status"] == target

    # Voice must not be entitled yet — only DEPLOYMENT_PENDING has happened so
    # far, which mirrors to PENDING_ACTIVATION, not ACTIVE (spec section 8:
    # a Voice lead/project never automatically grants an active entitlement).
    employees_resp = await client.get("/api/v1/employees", headers=org_scoped_headers)
    voice_employee = next(e for e in employees_resp.json() if e["type"] == "voice")
    assert voice_employee["status"] == "pending_activation"

    # 4. Final transition to ACTIVE mirrors the shared EmployeeProvision to ACTIVE.
    final_resp = await client.post(
        f"/api/v1/internal/voice-projects/{project_id}/transition",
        json={"targetStatus": "active"},
        headers=staff_headers,
    )
    assert final_resp.status_code == 200
    assert final_resp.json()["status"] == "active"

    employees_resp = await client.get("/api/v1/employees", headers=org_scoped_headers)
    voice_employee = next(e for e in employees_resp.json() if e["type"] == "voice")
    assert voice_employee["status"] == "active"


async def test_lead_rate_limit_blocks_excessive_public_submissions(client: AsyncClient) -> None:
    for _ in range(10):
        resp = await client.post(
            "/api/v1/leads/demo",
            json={"contactName": "Spam Bot", "contactEmail": "spam@example.com"},
        )
        assert resp.status_code == 201

    blocked_resp = await client.post(
        "/api/v1/leads/demo",
        json={"contactName": "Spam Bot", "contactEmail": "spam@example.com"},
    )
    assert blocked_resp.status_code == 429
    assert blocked_resp.json()["error"]["code"] == "RATE_LIMITED"
