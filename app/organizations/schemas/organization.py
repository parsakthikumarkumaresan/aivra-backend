from __future__ import annotations

from pydantic import Field

from app.shared.schemas.base import CamelModel


class OrganizationResponse(CamelModel):
    id: str
    name: str
    slug: str
    industry: str | None
    timezone: str
    status: str


class UpdateOrganizationRequest(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = None
    timezone: str | None = None


class CreateOrganizationRequest(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    industry: str | None = None
    timezone: str = "UTC"


class OrganizationMemberResponse(CamelModel):
    id: str
    user_id: str
    email: str
    full_name: str
    role: str
    status: str


class InviteMemberRequest(CamelModel):
    email: str
    role: str
