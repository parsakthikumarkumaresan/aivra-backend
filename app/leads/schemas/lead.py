from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from app.shared.schemas.base import CamelModel


class DemoLeadRequest(CamelModel):
    contact_name: str = Field(min_length=1, max_length=255)
    contact_email: EmailStr
    company_name: str | None = None
    phone: str | None = None
    message: str | None = None


class VoiceCustomizationRequest(CamelModel):
    contact_name: str = Field(min_length=1, max_length=255)
    contact_email: EmailStr
    company_name: str | None = None
    phone: str | None = None
    message: str | None = None
    project_name: str = Field(min_length=1, max_length=255)


class LeadResponse(CamelModel):
    id: str
    type: str
    status: str
    contact_name: str
    contact_email: str
    company_name: str | None
    phone: str | None
    message: str | None
    organization_id: str | None
    created_at: datetime


class ConvertLeadRequest(CamelModel):
    organization_id: str


class VoiceCustomizationResponse(CamelModel):
    lead: LeadResponse
    voice_project_id: str
