"""Public lead intake (spec section 16). No authentication — these are the
backend for marketing-site "Request a demo" / "Customize a Voice Employee"
forms. Rate-limited at the API layer (app.shared.security.rate_limit).
"""

from __future__ import annotations

from app.leads.models.lead import LEAD_TRANSITIONS, Lead, LeadStatus, LeadType
from app.leads.models.voice_project import VoiceProject
from app.leads.repositories.lead_repository import LeadRepository
from app.leads.repositories.voice_project_repository import VoiceProjectRepository
from app.shared.errors.exceptions import ConflictError, NotFoundError


class LeadService:
    def __init__(
        self, lead_repo: LeadRepository, voice_project_repo: VoiceProjectRepository
    ) -> None:
        self.lead_repo = lead_repo
        self.voice_project_repo = voice_project_repo

    async def submit_demo_request(
        self,
        *,
        contact_name: str,
        contact_email: str,
        company_name: str | None,
        phone: str | None,
        message: str | None,
    ) -> Lead:
        lead = Lead(
            type=LeadType.DEMO_REQUEST,
            contact_name=contact_name,
            contact_email=contact_email,
            company_name=company_name,
            phone=phone,
            message=message,
        )
        return await self.lead_repo.add(lead)

    async def submit_voice_customization_request(
        self,
        *,
        contact_name: str,
        contact_email: str,
        company_name: str | None,
        phone: str | None,
        message: str | None,
        project_name: str,
    ) -> tuple[Lead, VoiceProject]:
        lead = Lead(
            type=LeadType.VOICE_CUSTOMIZATION,
            contact_name=contact_name,
            contact_email=contact_email,
            company_name=company_name,
            phone=phone,
            message=message,
        )
        lead = await self.lead_repo.add(lead)

        project = VoiceProject(lead_id=lead.id, name=project_name)
        project = await self.voice_project_repo.add(project)
        return lead, project

    async def list_leads(self) -> list[Lead]:
        return await self.lead_repo.list_all()

    async def search_leads(
        self, *, query: str | None, status: LeadStatus | None, page: int, page_size: int
    ) -> tuple[list[Lead], int]:
        return await self.lead_repo.search_and_count(
            query=query, status=status, page=page, page_size=page_size
        )

    async def get_lead(self, lead_id: str) -> Lead:
        lead = await self.lead_repo.get_by_id(lead_id)
        if lead is None:
            raise NotFoundError("Lead not found.")
        return lead

    async def convert_lead(self, *, lead_id: str, organization_id: str) -> Lead:
        lead = await self.get_lead(lead_id)
        if lead.status == LeadStatus.CONVERTED:
            raise ConflictError("This lead has already been converted.")
        lead.status = LeadStatus.CONVERTED
        lead.organization_id = organization_id
        return lead

    async def transition(self, lead_id: str, target_status: LeadStatus) -> Lead:
        """Sales-triage stage change (Phase 6) — new/contacted/qualified/
        rejected only. Reaching CONVERTED still requires convert_lead
        (which also attaches organization_id); LEAD_TRANSITIONS has no
        edge into CONVERTED, so the backend rejects any attempt to reach
        it through this path.
        """
        lead = await self.get_lead(lead_id)
        LEAD_TRANSITIONS.assert_transition_allowed(lead.status, target_status)
        lead.status = target_status
        return lead

    async def get_voice_project_for_lead(self, lead_id: str) -> VoiceProject | None:
        projects = await self.voice_project_repo.list_for_leads([lead_id])
        return projects[0] if projects else None
