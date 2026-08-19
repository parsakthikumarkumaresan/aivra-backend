from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.identity.repositories.session_repository import SessionRepository
from app.identity.repositories.user_repository import UserRepository
from app.identity.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    SelectOrganizationRequest,
    UserResponse,
)
from app.identity.services.auth_service import AuthResult, AuthService
from app.organizations.repositories.membership_repository import MembershipRepository
from app.shared.database.session import get_db
from app.shared.errors.exceptions import AuthenticationRequiredError
from app.shared.security.csrf import CSRF_HEADER_NAME, verify_csrf
from app.shared.security.dependencies import AuthContext, get_auth_context
from app.shared.security.rate_limit import rate_limit
from app.shared.security.tokens import generate_csrf_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), SessionRepository(db), MembershipRepository(db))


def _set_auth_cookies(response: Response, result: AuthResult) -> None:
    settings = get_settings()
    secure = not settings.is_local
    if result.refresh_token:
        response.set_cookie(
            settings.refresh_cookie_name,
            result.refresh_token,
            max_age=result.refresh_token_ttl_seconds,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/api/v1/auth",
        )
    csrf_token = generate_csrf_token()
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=result.refresh_token_ttl_seconds or result.access_token_ttl_seconds,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _to_auth_response(result: AuthResult) -> AuthResponse:
    return AuthResponse(
        user=UserResponse(
            id=result.user.id,
            email=result.user.email,
            full_name=result.user.full_name,
            platform_role=result.user.platform_role,
            is_active=result.user.is_active,
        ),
        access_token=result.access_token,
        expires_in=result.access_token_ttl_seconds,
        organization_id=result.organization_id,
        role=result.role,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    payload: RegisterRequest, service: AuthService = Depends(_auth_service)
) -> UserResponse:
    user = await service.register(
        email=payload.email, password=payload.password, full_name=payload.full_name
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        platform_role=user.platform_role,
        is_active=user.is_active,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(_auth_service),
    _rate_limited: None = Depends(
        rate_limit(key_prefix="auth-login", max_requests=20, window_seconds=300)
    ),
) -> AuthResponse:
    result = await service.login(
        email=payload.email,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_auth_cookies(response, result)
    return _to_auth_response(result)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request, response: Response, service: AuthService = Depends(_auth_service)
) -> AuthResponse:
    settings = get_settings()
    raw_refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_refresh_token:
        raise AuthenticationRequiredError("No refresh token present.")
    verify_csrf(request)

    result = await service.refresh(raw_refresh_token=raw_refresh_token)
    _set_auth_cookies(response, result)
    return _to_auth_response(result)


@router.post("/logout", status_code=204, response_model=None)
async def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    service: AuthService = Depends(_auth_service),
) -> None:
    verify_csrf(request)
    await service.logout(session_id=auth.claims.session_id)
    settings = get_settings()
    response.delete_cookie(settings.refresh_cookie_name, path="/api/v1/auth")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.post("/select-organization", response_model=AuthResponse)
async def select_organization(
    payload: SelectOrganizationRequest,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    service: AuthService = Depends(_auth_service),
) -> AuthResponse:
    verify_csrf(request)
    result = await service.select_organization(
        user=auth.user, session_id=auth.claims.session_id, organization_id=payload.organization_id
    )
    _set_auth_cookies(response, result)
    return _to_auth_response(result)


@router.get("/me", response_model=UserResponse)
async def me(auth: AuthContext = Depends(get_auth_context)) -> UserResponse:
    return UserResponse(
        id=auth.user.id,
        email=auth.user.email,
        full_name=auth.user.full_name,
        platform_role=auth.user.platform_role,
        is_active=auth.user.is_active,
    )


__all__ = ["router", "CSRF_HEADER_NAME"]
