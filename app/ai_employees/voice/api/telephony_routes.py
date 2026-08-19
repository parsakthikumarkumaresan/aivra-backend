from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.voice.api.dependencies import require_voice_internal_role
from app.ai_employees.voice.models.routing_rule import RoutingCondition
from app.ai_employees.voice.models.telephony_provider import TelephonyProviderType
from app.ai_employees.voice.repositories.telephony_repository import (
    ComplianceRecordRepository,
    DndEntryRepository,
    PhoneNumberRepository,
    RoutingRuleRepository,
    SipTrunkRepository,
    TelephonyProviderAccountRepository,
)
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.ai_employees.voice.services.telephony_service import TelephonyService
from app.audit.models.audit_event import ActorType
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.shared.database.session import get_db
from app.shared.schemas.base import CamelModel
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/internal/telephony", tags=["Internal Telephony"])


# -- Request Schemas --
class ConnectProviderRequest(CamelModel):
    provider_type: TelephonyProviderType
    account_label: str | None = None
    credential_ref: str | None = None


class AddPhoneNumberRequest(CamelModel):
    number: str
    country: str = "US"
    provider_account_id: str
    monthly_cost: float = 0.0
    currency: str = "USD"


class AssignPhoneNumberRequest(CamelModel):
    voice_agent_id: str


class CreateSipTrunkRequest(CamelModel):
    name: str
    provider_account_id: str
    host: str
    codec: str = "OPUS"


class SetComplianceRecordRequest(CamelModel):
    label: str
    region: str
    enabled: bool
    description: str | None = None


class AddDndEntryRequest(CamelModel):
    number: str
    reason: str | None = None


class CreateRoutingRuleRequest(CamelModel):
    name: str
    condition: RoutingCondition
    destination: str
    priority: int = 0


# -- Endpoints --
@router.get("/providers")
async def list_telephony_providers(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    org_id = auth.require_organization_id()
    repo = TelephonyProviderAccountRepository(db)
    accounts = await repo.list_for_organization(org_id)
    return [
        {
            "id": a.id,
            "providerType": a.provider_type.value,
            "accountLabel": a.account_label,
            "status": a.status.value,
        }
        for a in accounts
    ]


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def connect_telephony_provider(
    req: ConnectProviderRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    account = await service.connect_provider_account(
        org_id, req.provider_type, req.account_label, req.credential_ref
    )
    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="telephony_provider.connected",
        resource_type="telephony_provider_account",
        resource_id=account.id,
    )
    return {
        "id": account.id,
        "providerType": account.provider_type.value,
        "accountLabel": account.account_label,
        "status": account.status.value,
    }


@router.get("/numbers")
async def list_phone_numbers(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    org_id = auth.require_organization_id()
    repo = PhoneNumberRepository(db)
    numbers = await repo.list_for_organization(org_id)
    return [
        {
            "id": n.id,
            "number": n.number,
            "country": n.country,
            "providerAccountId": n.provider_account_id,
            "status": n.status.value,
            "monthlyCost": float(n.monthly_cost),
            "currency": n.currency,
        }
        for n in numbers
    ]


@router.post("/numbers", status_code=status.HTTP_201_CREATED)
async def add_phone_number(
    req: AddPhoneNumberRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    phone = await service.add_phone_number(
        org_id, req.number, req.country, req.provider_account_id, req.monthly_cost, req.currency
    )
    return {
        "id": phone.id,
        "number": phone.number,
        "country": phone.country,
        "providerAccountId": phone.provider_account_id,
        "status": phone.status.value,
    }


@router.post("/numbers/{phone_number_id}/assign")
async def assign_phone_number(
    phone_number_id: str,
    req: AssignPhoneNumberRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    phone = await service.assign_phone_number_to_agent(
        org_id, phone_number_id, req.voice_agent_id
    )
    await AuditService(AuditRepository(db)).record(
        organization_id=org_id,
        actor_id=auth.user.id,
        actor_type=ActorType.USER,
        action="phone_number.assigned",
        resource_type="phone_number",
        resource_id=phone.id,
    )
    return {"id": phone.id, "status": phone.status.value, "assignedAgentId": req.voice_agent_id}


@router.post("/numbers/{phone_number_id}/unassign")
async def unassign_phone_number(
    phone_number_id: str,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    phone = await service.unassign_phone_number(org_id, phone_number_id)
    return {"id": phone.id, "status": phone.status.value}


@router.get("/trunks")
async def list_sip_trunks(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    org_id = auth.require_organization_id()
    repo = SipTrunkRepository(db)
    trunks = await repo.list_for_organization(org_id)
    return [
        {
            "id": t.id,
            "name": t.name,
            "host": t.host,
            "status": t.status.value,
            "codec": t.codec,
        }
        for t in trunks
    ]


@router.post("/trunks", status_code=status.HTTP_201_CREATED)
async def create_sip_trunk(
    req: CreateSipTrunkRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    trunk = await service.create_sip_trunk(
        org_id, req.name, req.provider_account_id, req.host, req.codec
    )
    return {"id": trunk.id, "name": trunk.name, "host": trunk.host, "status": trunk.status.value}


@router.get("/compliance")
async def list_compliance(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    org_id = auth.require_organization_id()
    repo = ComplianceRecordRepository(db)
    records = await repo.list_for_organization(org_id)
    return [
        {"id": r.id, "label": r.label, "region": r.region, "enabled": r.enabled} for r in records
    ]


@router.post("/compliance", status_code=status.HTTP_201_CREATED)
async def set_compliance(
    req: SetComplianceRecordRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    record = await service.set_compliance_record(
        org_id, req.label, req.region, req.enabled, req.description
    )
    return {
        "id": record.id,
        "label": record.label,
        "region": record.region,
        "enabled": record.enabled,
    }


@router.get("/dnd")
async def list_dnd_entries(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    org_id = auth.require_organization_id()
    repo = DndEntryRepository(db)
    entries = await repo.list_for_organization(org_id)
    return [
        {"id": e.id, "number": e.number, "reason": e.reason, "addedAt": e.added_at.isoformat()}
        for e in entries
    ]


@router.post("/dnd", status_code=status.HTTP_201_CREATED)
async def add_dnd_entry(
    req: AddDndEntryRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    entry = await service.add_dnd_entry(org_id, req.number, req.reason)
    return {"id": entry.id, "number": entry.number, "reason": entry.reason}


@router.get("/routes")
async def list_routing_rules(
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    org_id = auth.require_organization_id()
    repo = RoutingRuleRepository(db)
    rules = await repo.list_for_organization(org_id)
    return [
        {
            "id": r.id,
            "name": r.name,
            "condition": r.condition.value,
            "destination": r.destination,
            "enabled": r.enabled,
            "priority": r.priority,
        }
        for r in rules
    ]


@router.post("/routes", status_code=status.HTTP_201_CREATED)
async def create_routing_rule(
    req: CreateRoutingRuleRequest,
    auth: AuthContext = Depends(require_voice_internal_role()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = auth.require_organization_id()
    service = TelephonyService(
        PhoneNumberRepository(db),
        TelephonyProviderAccountRepository(db),
        SipTrunkRepository(db),
        ComplianceRecordRepository(db),
        DndEntryRepository(db),
        RoutingRuleRepository(db),
        VoiceAgentRepository(db),
    )
    rule = await service.create_routing_rule(
        org_id, req.name, req.condition, req.destination, req.priority
    )
    return {
        "id": rule.id,
        "name": rule.name,
        "condition": rule.condition.value,
        "destination": rule.destination,
        "enabled": rule.enabled,
        "priority": rule.priority,
    }
