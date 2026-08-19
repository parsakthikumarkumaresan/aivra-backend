"""Public lead intake + AIVRA-internal lead triage.

Public endpoints (no auth) power marketing-site forms and are rate-limited
per client IP. Internal endpoints require an AIVRA platform role — leads
and Voice project management are AIVRA operational data, not customer-
facing (spec sections 14, 16).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.repositories.lead_repository import LeadRepository
from app.leads.repositories.voice_project_repository import VoiceProjectRepository
from app.leads.schemas.lead import (
    ConvertLeadRequest,
    DemoLeadRequest,
    LeadResponse,
    VoiceCustomizationRequest,
    VoiceCustomizationResponse,
)
from app.leads.services.lead_service import LeadService
from app.shared.database.session import get_db
from app.shared.rbac.roles import PlatformRole
from app.shared.security.dependencies import require_platform_role
from app.shared.security.rate_limit import rate_limit

router = APIRouter(prefix="/leads", tags=["leads"])

_INTERNAL_ROLES = (PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER)


def _service(db: AsyncSession = Depends(get_db)) -> LeadService:
    return LeadService(LeadRepository(db), VoiceProjectRepository(db))


@router.post(
    "/demo",
    response_model=LeadResponse,
    status_code=201,
    dependencies=[
        Depends(rate_limit(key_prefix="leads-demo", max_requests=10, window_seconds=600))
    ],
)
async def submit_demo_request(
    payload: DemoLeadRequest, service: LeadService = Depends(_service)
) -> LeadResponse:
    lead = await service.submit_demo_request(
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        company_name=payload.company_name,
        phone=payload.phone,
        message=payload.message,
    )
    return LeadResponse.model_validate(lead)


@router.post(
    "/voice-customization",
    response_model=VoiceCustomizationResponse,
    status_code=201,
    dependencies=[
        Depends(rate_limit(key_prefix="leads-voice", max_requests=10, window_seconds=600))
    ],
)
async def submit_voice_customization_request(
    payload: VoiceCustomizationRequest, service: LeadService = Depends(_service)
) -> VoiceCustomizationResponse:
    lead, project = await service.submit_voice_customization_request(
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        company_name=payload.company_name,
        phone=payload.phone,
        message=payload.message,
        project_name=payload.project_name,
    )
    return VoiceCustomizationResponse(
        lead=LeadResponse.model_validate(lead), voice_project_id=project.id
    )


@router.get(
    "",
    response_model=list[LeadResponse],
    dependencies=[Depends(require_platform_role(*_INTERNAL_ROLES))],
)
async def list_leads(service: LeadService = Depends(_service)) -> list[LeadResponse]:
    leads = await service.list_leads()
    return [LeadResponse.model_validate(lead) for lead in leads]


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require_platform_role(*_INTERNAL_ROLES))],
)
async def get_lead(lead_id: str, service: LeadService = Depends(_service)) -> LeadResponse:
    lead = await service.get_lead(lead_id)
    return LeadResponse.model_validate(lead)


@router.post(
    "/{lead_id}/convert",
    response_model=LeadResponse,
    dependencies=[Depends(require_platform_role(*_INTERNAL_ROLES))],
)
async def convert_lead(
    lead_id: str, payload: ConvertLeadRequest, service: LeadService = Depends(_service)
) -> LeadResponse:
    lead = await service.convert_lead(lead_id=lead_id, organization_id=payload.organization_id)
    return LeadResponse.model_validate(lead)
