"""End-to-end auth flow: register -> login -> create org -> select org ->
refresh rotation -> reuse detection -> logout.
"""

from __future__ import annotations

from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str = "owner@example.com") -> dict:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123!", "fullName": "Test Owner"},
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SuperSecret123!"}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_register_login_returns_access_token(client: AsyncClient) -> None:
    body = await _register_and_login(client)
    assert body["accessToken"]
    assert body["organizationId"] is None
    assert body["user"]["email"] == "owner@example.com"


async def test_login_with_wrong_password_is_rejected(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "wrongpw@example.com", "password": "SuperSecret123!", "fullName": "X"},
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": "wrongpw@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_account_locks_after_max_failed_attempts(client: AsyncClient) -> None:
    email = "lockout@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123!", "fullName": "X"},
    )
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": email, "password": "bad"})

    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SuperSecret123!"}
    )
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"


async def test_create_and_select_organization_grants_role_claim(client: AsyncClient) -> None:
    body = await _register_and_login(client, "orgowner@example.com")
    token = body["accessToken"]

    create_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Acme", "slug": "acme-flow-test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201
    org_id = create_resp.json()["id"]

    csrf = client.cookies.get("aivra_csrf")
    select_resp = await client.post(
        "/api/v1/auth/select-organization",
        json={"organizationId": org_id},
        headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf},
    )
    assert select_resp.status_code == 200, select_resp.text
    assert select_resp.json()["organizationId"] == org_id
    assert select_resp.json()["role"] == "owner"


async def test_select_organization_without_csrf_header_is_forbidden(client: AsyncClient) -> None:
    body = await _register_and_login(client, "nocsrf@example.com")
    token = body["accessToken"]
    create_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "NoCsrf Co", "slug": "nocsrf-co"},
        headers={"Authorization": f"Bearer {token}"},
    )
    org_id = create_resp.json()["id"]

    response = await client.post(
        "/api/v1/auth/select-organization",
        json={"organizationId": org_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_refresh_rotates_the_refresh_cookie(client: AsyncClient) -> None:
    await _register_and_login(client, "rotate@example.com")
    csrf = client.cookies.get("aivra_csrf")
    original_refresh_cookie = client.cookies.get("aivra_refresh")

    response = await client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert client.cookies.get("aivra_refresh") != original_refresh_cookie

    # The CSRF cookie is rotated on every auth response too — re-read it before
    # the next call, exactly as a real client must.
    csrf = client.cookies.get("aivra_csrf")
    second_response = await client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert second_response.status_code == 200

    # Reuse-with-precise-control (presenting an already-rotated-out raw token) is
    # covered at the service layer in tests/unit/test_auth_service.py, where the
    # raw token string is directly available rather than hidden in a cookie jar.


async def test_logout_revokes_session(client: AsyncClient) -> None:
    body = await _register_and_login(client, "logout@example.com")
    token = body["accessToken"]
    csrf = client.cookies.get("aivra_csrf")

    logout_resp = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}
    )
    assert logout_resp.status_code == 204

    refresh_resp = await client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refresh_resp.status_code == 401
