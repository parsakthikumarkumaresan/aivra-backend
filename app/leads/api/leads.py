"""Public lead intake + AIVRA-internal lead triage.

Public endpoints (no auth) power marketing-site forms and are rate-limited
per client IP. Internal endpoints require an AIVRA platform role — leads
and Voice project management are AIVRA operational data, not customer-
facing (spec sections 14, 16).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import ActorType
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.leads.models.lead import Lead, LeadStatus
from app.leads.repositories.lead_repository import LeadRepository
from app.leads.repositories.voice_project_repository import VoiceProjectRepository
from app.leads.schemas.lead import (
    AdminLeadListResponse,
    AdminLeadResponse,
    AdminLeadVoiceProjectSummary,
    ConvertLeadRequest,
    DemoLeadRequest,
    LeadResponse,
    TransitionLeadRequest,
    VoiceCustomizationRequest,
    VoiceCustomizationResponse,
)
from app.leads.services.lead_service import LeadService
from app.shared.database.session import get_db
from app.shared.rbac.roles import PlatformRole
from app.shared.security.dependencies import AuthContext, require_platform_role
from app.shared.security.rate_limit import rate_limit

router = APIRouter(prefix="/leads", tags=["leads"])

_INTERNAL_ROLES = (PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER)


def _service(db: AsyncSession = Depends(get_db)) -> LeadService:
    return LeadService(LeadRepository(db), VoiceProjectRepository(db))


async def _to_admin_response(lead: Lead, service: LeadService) -> AdminLeadResponse:
    project = await service.get_voice_project_for_lead(lead.id)
    return AdminLeadResponse(
        id=lead.id,
        type=lead.type.value,
        status=lead.status.value,
        contact_name=lead.contact_name,
        contact_email=lead.contact_email,
        company_name=lead.company_name,
        phone=lead.phone,
        message=lead.message,
        organization_id=lead.organization_id,
        created_at=lead.created_at,
        voice_project=(
            AdminLeadVoiceProjectSummary(
                id=project.id, name=project.name, status=project.status.value
            )
            if project
            else None
        ),
    )


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
    response_model=AdminLeadListResponse,
    dependencies=[Depends(require_platform_role(*_INTERNAL_ROLES))],
)
async def list_leads(
    search: str | None = Query(default=None, max_length=255),
    status: LeadStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    service: LeadService = Depends(_service),
) -> AdminLeadListResponse:
    leads, total = await service.search_leads(
        query=search, status=status, page=page, page_size=page_size
    )
    lead_ids = [lead.id for lead in leads]
    projects = await service.voice_project_repo.list_for_leads(lead_ids)
    projects_by_lead = {p.lead_id: p for p in projects}

    items = [
        AdminLeadResponse(
            id=lead.id,
            type=lead.type.value,
            status=lead.status.value,
            contact_name=lead.contact_name,
            contact_email=lead.contact_email,
            company_name=lead.company_name,
            phone=lead.phone,
            message=lead.message,
            organization_id=lead.organization_id,
            created_at=lead.created_at,
            voice_project=(
                AdminLeadVoiceProjectSummary(
                    id=projects_by_lead[lead.id].id,
                    name=projects_by_lead[lead.id].name,
                    status=projects_by_lead[lead.id].status.value,
                )
                if lead.id in projects_by_lead
                else None
            ),
        )
        for lead in leads
    ]
    return AdminLeadListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/{lead_id}",
    response_model=AdminLeadResponse,
    dependencies=[Depends(require_platform_role(*_INTERNAL_ROLES))],
)
async def get_lead(lead_id: str, service: LeadService = Depends(_service)) -> AdminLeadResponse:
    lead = await service.get_lead(lead_id)
    return await _to_admin_response(lead, service)


@router.post("/{lead_id}/convert", response_model=LeadResponse)
async def convert_lead(
    lead_id: str,
    payload: ConvertLeadRequest,
    auth: AuthContext = Depends(require_platform_role(*_INTERNAL_ROLES)),
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(_service),
) -> LeadResponse:
    lead = await service.convert_lead(lead_id=lead_id, organization_id=payload.organization_id)
    await AuditService(AuditRepository(db)).record(
        organization_id=payload.organization_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="lead.converted",
        resource_type="lead",
        resource_id=lead.id,
    )
    return LeadResponse.model_validate(lead)


@router.post("/{lead_id}/transition", response_model=AdminLeadResponse)
async def transition_lead(
    lead_id: str,
    payload: TransitionLeadRequest,
    auth: AuthContext = Depends(require_platform_role(*_INTERNAL_ROLES)),
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(_service),
) -> AdminLeadResponse:
    """Sales-triage stage change only (new/contacted/qualified/rejected) —
    the backend's LEAD_TRANSITIONS state machine is the sole authority;
    an invalid transition raises INVALID_STATE_TRANSITION (409) regardless
    of what the frontend requests. Reaching 'converted' must go through
    POST /{lead_id}/convert instead.

    Not audit-logged: AuditEvent is organization-scoped (NOT NULL FK), and
    a lead has no organization_id until it converts — there is no
    organization to attribute this event to yet.
    """
    lead = await service.transition(lead_id, LeadStatus(payload.target_status))
    return await _to_admin_response(lead, service)
