from __future__ import annotations

from pydantic import EmailStr, Field

from app.shared.schemas.base import CamelModel


class RegisterRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SelectOrganizationRequest(CamelModel):
    organization_id: str


class UserResponse(CamelModel):
    id: str
    email: str
    full_name: str
    platform_role: str | None
    is_active: bool


class AuthResponse(CamelModel):
    user: UserResponse
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    organization_id: str | None
    role: str | None
