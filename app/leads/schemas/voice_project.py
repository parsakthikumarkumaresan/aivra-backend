from __future__ import annotations

from app.shared.schemas.base import CamelModel


class VoiceProjectResponse(CamelModel):
    id: str
    lead_id: str
    organization_id: str | None
    name: str
    status: str
    assigned_engineer_user_id: str | None
    failure_reason: str | None


class AssignOrganizationRequest(CamelModel):
    organization_id: str


class AssignEngineerRequest(CamelModel):
    engineer_user_id: str


class AddRequirementRequest(CamelModel):
    key: str
    value: str


class RequirementResponse(CamelModel):
    id: str
    key: str
    value: str


class TransitionVoiceProjectRequest(CamelModel):
    target_status: str
    failure_reason: str | None = None
