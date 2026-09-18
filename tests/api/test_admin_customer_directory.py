"""JEXA Admin — Customer Directory + Customer Detail (Phase 5): real
organization data, search, pagination, AI Employee visibility, platform-
role security, and cross-tenant reach (admin sees every org by design).
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.provisioning.models.provision import EmployeeProvision, ProvisionStatus
from app.ai_employees.registry.models.catalog import (
    AIEmployeeType,
    CommercialModel,
    EmployeeTypeCode,
)
from app.identity.models.user import User
from app.leads.models.lead import Lead, LeadStatus, LeadType
from app.leads.models.voice_project import VoiceProject, VoiceProjectStatus
from app.organizations.models.membership import OrganizationMember
from app.organizations.models.organization import Organization
from app.shared.rbac.roles import OrgRole, PlatformRole
from app.shared.security.tokens import create_access_token


async def _make_employee_type(session: AsyncSession, code: EmployeeTypeCode) -> AIEmployeeType:
    et = AIEmployeeType(
        code=code,
        name="HR" if code == EmployeeTypeCode.HR else "Voice",
        commercial_model=(
            CommercialModel.SELF_SERVICE_SUBSCRIPTION
            if code == EmployeeTypeCode.HR
            else CommercialModel.MANAGED_CUSTOM
        ),
    )
    session.add(et)
    await session.flush()
    return et


async def _admin_token(session: AsyncSession, email: str = "admin@aivra.ai") -> str:
    user = User(
        email=email, full_name="Admin", password_hash="hash", platform_role=PlatformRole.AIVRA_ADMIN
    )
    session.add(user)
    await session.flush()
    return create_access_token(
        user_id=user.id, organization_id=None, role=None, session_id=f"ses_{email}"
    )


@pytest.mark.asyncio
async def test_customer_directory_rejects_plain_customer(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = Organization(id="org_dir_reject", name="Reject Co", slug="org_dir_reject")
    db_session.add(org)
    user = User(email="customer@example.com", full_name="Customer", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrgRole.OWNER))
    await db_session.flush()
    token = create_access_token(
        user_id=user.id, organization_id=org.id, role=OrgRole.OWNER.value, session_id="ses_reject"
    )

    resp = await client.get(
        "/api/v1/internal/organizations", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_customer_directory_rejects_unauthenticated(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/internal/organizations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_customer_directory_lists_real_organizations_with_ai_employee_visibility(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    hr_type = await _make_employee_type(db_session, EmployeeTypeCode.HR)
    voice_type = await _make_employee_type(db_session, EmployeeTypeCode.VOICE)

    org = Organization(id="org_dir_visible", name="Acme Directory Co", slug="org_dir_visible")
    db_session.add(org)
    await db_session.flush()
    db_session.add_all(
        [
            EmployeeProvision(
                organization_id=org.id, employee_type_id=hr_type.id, status=ProvisionStatus.ACTIVE
            ),
            EmployeeProvision(
                organization_id=org.id,
                employee_type_id=voice_type.id,
                status=ProvisionStatus.PENDING_ACTIVATION,
            ),
        ]
    )
    await db_session.flush()

    token = await _admin_token(db_session)
    resp = await client.get(
        "/api/v1/internal/organizations", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["page"] == 1
    row = next(item for item in body["items"] if item["id"] == org.id)
    codes = {p["employeeTypeCode"]: p["status"] for p in row["employeeProvisions"]}
    assert codes == {"hr": "active", "voice": "pending_activation"}


@pytest.mark.asyncio
async def test_customer_directory_search_filters_by_name(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Organization(id="org_search_zeta", name="Zeta Logistics", slug="org_search_zeta"),
            Organization(id="org_search_omega", name="Omega Retail", slug="org_search_omega"),
        ]
    )
    await db_session.flush()
    token = await _admin_token(db_session, email="admin_search@aivra.ai")

    resp = await client.get(
        "/api/v1/internal/organizations",
        params={"search": "Zeta"},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert all("zeta" in item["name"].lower() for item in body["items"])
    assert any(item["id"] == "org_search_zeta" for item in body["items"])
    assert not any(item["id"] == "org_search_omega" for item in body["items"])


@pytest.mark.asyncio
async def test_customer_directory_pagination(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    for i in range(5):
        db_session.add(Organization(id=f"org_page_{i}", name=f"PagerCo {i}", slug=f"org-page-{i}"))
    await db_session.flush()
    token = await _admin_token(db_session, email="admin_page@aivra.ai")

    page1 = (
        await client.get(
            "/api/v1/internal/organizations",
            params={"search": "PagerCo", "page": 1, "pageSize": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    page2 = (
        await client.get(
            "/api/v1/internal/organizations",
            params={"search": "PagerCo", "page": 2, "pageSize": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()

    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page2["items"]})


@pytest.mark.asyncio
async def test_customer_detail_returns_provisions_projects_and_members(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    voice_type = await _make_employee_type(db_session, EmployeeTypeCode.VOICE)
    org = Organization(id="org_detail_1", name="Detail Co", slug="org_detail_1")
    db_session.add(org)
    owner = User(email="owner_detail@example.com", full_name="Owner Person", password_hash="hash")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role=OrgRole.OWNER))
    db_session.add(
        EmployeeProvision(
            organization_id=org.id, employee_type_id=voice_type.id, status=ProvisionStatus.ACTIVE
        )
    )
    lead = Lead(
        id="lead_detail_1",
        type=LeadType.VOICE_CUSTOMIZATION,
        status=LeadStatus.CONVERTED,
        contact_name="Owner Person",
        contact_email="owner_detail@example.com",
        organization_id=org.id,
    )
    db_session.add(lead)
    await db_session.flush()
    db_session.add(
        VoiceProject(
            id="vproj_detail_1",
            lead_id=lead.id,
            organization_id=org.id,
            name="Detail Co Jaan",
            status=VoiceProjectStatus.ACTIVE,
        )
    )
    await db_session.flush()

    token = await _admin_token(db_session, email="admin_detail@aivra.ai")
    resp = await client.get(
        f"/api/v1/internal/organizations/{org.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Detail Co"
    assert body["employeeProvisions"][0]["employeeTypeCode"] == "voice"
    assert body["voiceProjects"][0]["name"] == "Detail Co Jaan"
    assert body["members"][0]["email"] == "owner_detail@example.com"


@pytest.mark.asyncio
async def test_customer_detail_404s_for_unknown_organization(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(db_session, email="admin_404@aivra.ai")
    resp = await client.get(
        "/api/v1/internal/organizations/org_does_not_exist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
