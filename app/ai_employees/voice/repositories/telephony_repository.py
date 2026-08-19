from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.voice.models.compliance import ComplianceRecord, DndEntry
from app.ai_employees.voice.models.phone_number import PhoneNumber
from app.ai_employees.voice.models.routing_rule import RoutingRule
from app.ai_employees.voice.models.sip_trunk import SipTrunk
from app.ai_employees.voice.models.telephony_provider import TelephonyProviderAccount
from app.shared.database.repository import OrgScopedRepository


class PhoneNumberRepository(OrgScopedRepository[PhoneNumber]):
    model = PhoneNumber

    async def list_for_organization(self, organization_id: str) -> list[PhoneNumber]:
        stmt = select(PhoneNumber).where(PhoneNumber.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_number(self, organization_id: str, number: str) -> PhoneNumber | None:
        stmt = select(PhoneNumber).where(
            PhoneNumber.organization_id == organization_id,
            PhoneNumber.number == number,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class TelephonyProviderAccountRepository(OrgScopedRepository[TelephonyProviderAccount]):
    model = TelephonyProviderAccount

    async def list_for_organization(self, organization_id: str) -> list[TelephonyProviderAccount]:
        stmt = select(TelephonyProviderAccount).where(
            TelephonyProviderAccount.organization_id == organization_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class SipTrunkRepository(OrgScopedRepository[SipTrunk]):
    model = SipTrunk

    async def list_for_organization(self, organization_id: str) -> list[SipTrunk]:
        stmt = select(SipTrunk).where(SipTrunk.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ComplianceRecordRepository(OrgScopedRepository[ComplianceRecord]):
    model = ComplianceRecord

    async def list_for_organization(self, organization_id: str) -> list[ComplianceRecord]:
        stmt = select(ComplianceRecord).where(ComplianceRecord.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DndEntryRepository(OrgScopedRepository[DndEntry]):
    model = DndEntry

    async def list_for_organization(self, organization_id: str) -> list[DndEntry]:
        stmt = select(DndEntry).where(DndEntry.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_number(self, organization_id: str, number: str) -> DndEntry | None:
        stmt = select(DndEntry).where(
            DndEntry.organization_id == organization_id,
            DndEntry.number == number,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class RoutingRuleRepository(OrgScopedRepository[RoutingRule]):
    model = RoutingRule

    async def list_for_organization(self, organization_id: str) -> list[RoutingRule]:
        stmt = (
            select(RoutingRule)
            .where(RoutingRule.organization_id == organization_id)
            .order_by(RoutingRule.priority.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
