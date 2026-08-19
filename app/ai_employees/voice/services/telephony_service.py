from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.voice.models.compliance import ComplianceRecord, DndEntry
from app.ai_employees.voice.models.phone_number import PhoneNumber, PhoneNumberStatus
from app.ai_employees.voice.models.routing_rule import RoutingCondition, RoutingRule
from app.ai_employees.voice.models.sip_trunk import SipTrunk, SipTrunkStatus
from app.ai_employees.voice.models.telephony_provider import (
    TelephonyAccountStatus,
    TelephonyProviderAccount,
    TelephonyProviderType,
)
from app.ai_employees.voice.repositories.telephony_repository import (
    ComplianceRecordRepository,
    DndEntryRepository,
    PhoneNumberRepository,
    RoutingRuleRepository,
    SipTrunkRepository,
    TelephonyProviderAccountRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.shared.errors.exceptions import NotFoundError


class TelephonyService:
    def __init__(
        self,
        phone_repo: PhoneNumberRepository,
        account_repo: TelephonyProviderAccountRepository,
        sip_repo: SipTrunkRepository,
        compliance_repo: ComplianceRecordRepository,
        dnd_repo: DndEntryRepository,
        routing_repo: RoutingRuleRepository,
        agent_repo: VoiceAgentRepository,
    ) -> None:
        self.phone_repo = phone_repo
        self.account_repo = account_repo
        self.sip_repo = sip_repo
        self.compliance_repo = compliance_repo
        self.dnd_repo = dnd_repo
        self.routing_repo = routing_repo
        self.agent_repo = agent_repo

    # -- Telephony Provider Accounts --
    async def list_provider_accounts(
        self, organization_id: str
    ) -> list[TelephonyProviderAccount]:
        return await self.account_repo.list_for_organization(organization_id)

    async def connect_provider_account(
        self,
        organization_id: str,
        provider_type: TelephonyProviderType,
        account_label: str | None = None,
        credential_ref: str | None = None,
    ) -> TelephonyProviderAccount:
        account = TelephonyProviderAccount(
            organization_id=organization_id,
            provider_type=provider_type,
            account_label=account_label,
            credential_ref=credential_ref,
            status=TelephonyAccountStatus.CONNECTED,
        )
        return await self.account_repo.add(account)

    # -- Phone Numbers --
    async def list_phone_numbers(self, organization_id: str) -> list[PhoneNumber]:
        return await self.phone_repo.list_for_organization(organization_id)

    async def get_phone_number(self, organization_id: str, phone_number_id: str) -> PhoneNumber:
        number = await self.phone_repo.get_by_id(organization_id, phone_number_id)
        if number is None:
            raise NotFoundError("Phone number not found.")
        return number

    async def add_phone_number(
        self,
        organization_id: str,
        number: str,
        country: str,
        provider_account_id: str,
        monthly_cost: float = 0.0,
        currency: str = "USD",
    ) -> PhoneNumber:
        account = await self.account_repo.get_by_id(organization_id, provider_account_id)
        if account is None:
            raise NotFoundError("Telephony provider account not found.")

        phone = PhoneNumber(
            organization_id=organization_id,
            number=number,
            country=country,
            provider_account_id=provider_account_id,
            status=PhoneNumberStatus.UNASSIGNED,
            monthly_cost=monthly_cost,
            currency=currency,
        )
        return await self.phone_repo.add(phone)

    async def assign_phone_number_to_agent(
        self, organization_id: str, phone_number_id: str, agent_id: str
    ) -> PhoneNumber:
        phone = await self.get_phone_number(organization_id, phone_number_id)
        agent = await self.agent_repo.get_by_id(organization_id, agent_id)
        if agent is None:
            raise NotFoundError("Voice agent not found.")

        agent.assigned_phone_number_id = phone.id
        phone.status = PhoneNumberStatus.ACTIVE
        return phone

    async def unassign_phone_number(
        self, organization_id: str, phone_number_id: str
    ) -> PhoneNumber:
        phone = await self.get_phone_number(organization_id, phone_number_id)
        agents = await self.agent_repo.list_for_organization(organization_id)
        for agent in agents:
            if agent.assigned_phone_number_id == phone.id:
                agent.assigned_phone_number_id = None

        phone.status = PhoneNumberStatus.UNASSIGNED
        return phone

    # -- SIP Trunks --
    async def list_sip_trunks(self, organization_id: str) -> list[SipTrunk]:
        return await self.sip_repo.list_for_organization(organization_id)

    async def create_sip_trunk(
        self,
        organization_id: str,
        name: str,
        provider_account_id: str,
        host: str,
        codec: str = "OPUS",
    ) -> SipTrunk:
        trunk = SipTrunk(
            organization_id=organization_id,
            name=name,
            provider_account_id=provider_account_id,
            host=host,
            codec=codec,
            status=SipTrunkStatus.ACTIVE,
        )
        return await self.sip_repo.add(trunk)

    # -- Compliance & DND --
    async def list_compliance_records(self, organization_id: str) -> list[ComplianceRecord]:
        return await self.compliance_repo.list_for_organization(organization_id)

    async def set_compliance_record(
        self,
        organization_id: str,
        label: str,
        region: str,
        enabled: bool,
        description: str | None = None,
    ) -> ComplianceRecord:
        record = ComplianceRecord(
            organization_id=organization_id,
            label=label,
            region=region,
            enabled=enabled,
            description=description,
        )
        return await self.compliance_repo.add(record)

    async def list_dnd_entries(self, organization_id: str) -> list[DndEntry]:
        return await self.dnd_repo.list_for_organization(organization_id)

    async def add_dnd_entry(
        self, organization_id: str, number: str, reason: str | None = None
    ) -> DndEntry:
        existing = await self.dnd_repo.get_by_number(organization_id, number)
        if existing:
            return existing
        entry = DndEntry(
            organization_id=organization_id,
            number=number,
            reason=reason,
            added_at=datetime.now(UTC),
        )
        return await self.dnd_repo.add(entry)

    async def is_dnd(self, organization_id: str, number: str) -> bool:
        entry = await self.dnd_repo.get_by_number(organization_id, number)
        return entry is not None

    # -- Routing Rules --
    async def list_routing_rules(self, organization_id: str) -> list[RoutingRule]:
        return await self.routing_repo.list_for_organization(organization_id)

    async def create_routing_rule(
        self,
        organization_id: str,
        name: str,
        condition: RoutingCondition,
        destination: str,
        priority: int = 0,
    ) -> RoutingRule:
        rule = RoutingRule(
            organization_id=organization_id,
            name=name,
            condition=condition,
            destination=destination,
            priority=priority,
            enabled=True,
        )
        return await self.routing_repo.add(rule)
