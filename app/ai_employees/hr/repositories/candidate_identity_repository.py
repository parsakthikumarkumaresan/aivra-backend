from __future__ import annotations

from sqlalchemy import select

from app.ai_employees.hr.models.candidate import CandidateIdentity
from app.shared.database.repository import OrgScopedRepository


class CandidateIdentityRepository(OrgScopedRepository[CandidateIdentity]):
    model = CandidateIdentity

    async def find_by_email(self, organization_id: str, email: str) -> CandidateIdentity | None:
        stmt = select(CandidateIdentity).where(
            CandidateIdentity.organization_id == organization_id,
            CandidateIdentity.email == email,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_ids(
        self, organization_id: str, ids: list[str]
    ) -> dict[str, CandidateIdentity]:
        if not ids:
            return {}
        stmt = select(CandidateIdentity).where(
            CandidateIdentity.organization_id == organization_id,
            CandidateIdentity.id.in_(ids),
        )
        result = await self.session.execute(stmt)
        return {identity.id: identity for identity in result.scalars().all()}
