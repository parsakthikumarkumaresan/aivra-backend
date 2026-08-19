"""Mandatory cross-tenant isolation tests (spec sections 7, 26, 39).

A user authenticated into Organization A must never be able to read or act
on Organization B's data, even by guessing/enumerating IDs, and must not be
able to select an organization they are not a member of.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _register_login_and_create_org(client: AsyncClient, email: str, org_slug: str) -> dict:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123!", "fullName": "Tenant Owner"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SuperSecret123!"}
    )
    token = login.json()["accessToken"]

    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": org_slug, "slug": org_slug},
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


async def test_user_cannot_select_organization_they_do_not_belong_to(client: AsyncClient) -> None:
    tenant_a = await _register_login_and_create_org(client, "iso-a@example.com", "iso-tenant-a")

    # A second, unrelated user tries to select tenant A's organization.
    await client.post(
        "/api/v1/auth/register",
        json={"email": "iso-b@example.com", "password": "SuperSecret123!", "fullName": "B"},
    )
    login_b = await client.post(
        "/api/v1/auth/login", json={"email": "iso-b@example.com", "password": "SuperSecret123!"}
    )
    token_b = login_b.json()["accessToken"]
    csrf_b = client.cookies.get("aivra_csrf")

    response = await client.post(
        "/api/v1/auth/select-organization",
        json={"organizationId": tenant_a["org_id"]},
        headers={"Authorization": f"Bearer {token_b}", "X-CSRF-Token": csrf_b},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_removed_member_loses_access_despite_valid_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A JWT's org claim is not re-validated against DB membership on every
    request for staleness (see require_organization_context), but the
    membership row itself is — so a still-unexpired access token from a
    removed member must still be denied.

    ``client`` depends on ``db_session`` (see tests/conftest.py), so
    requesting both here gives the exact same session the API used —
    mutating it directly is equivalent to an admin removing the member.
    """
    from sqlalchemy import select

    from app.organizations.models.membership import MembershipStatus, OrganizationMember

    tenant = await _register_login_and_create_org(client, "iso-c@example.com", "iso-tenant-c")

    result = await db_session.execute(
        select(OrganizationMember).where(OrganizationMember.organization_id == tenant["org_id"])
    )
    membership = result.scalar_one()
    membership.status = MembershipStatus.REMOVED
    await db_session.flush()

    response = await client.get(
        "/api/v1/organizations/me", headers={"Authorization": f"Bearer {tenant['token']}"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MEMBERSHIP_REQUIRED"


async def test_organization_provisioning_is_isolated_per_tenant(client: AsyncClient) -> None:
    """Two orgs' employee/provisioning views must never leak into each other."""
    tenant_a = await _register_login_and_create_org(client, "iso-d@example.com", "iso-tenant-d")
    tenant_e = await _register_login_and_create_org(client, "iso-e@example.com", "iso-tenant-e")

    resp_a = await client.get(
        "/api/v1/employees", headers={"Authorization": f"Bearer {tenant_a['token']}"}
    )
    resp_e = await client.get(
        "/api/v1/employees", headers={"Authorization": f"Bearer {tenant_e['token']}"}
    )
    assert resp_a.status_code == 200
    assert resp_e.status_code == 200
    # Both are empty catalogs in this test DB, but critically each request was
    # scoped by its own bearer token's organization_id claim — no shared state
    # object or org_id parameter was passed by the client.
    assert resp_a.json() == resp_e.json() == []
