from __future__ import annotations

from sqlalchemy import or_, select

from app.ai_employees.hr.models.candidate import Candidate, CandidateStage
from app.shared.database.repository import OrgScopedRepository


class CandidateRepository(OrgScopedRepository[Candidate]):
    model = Candidate

    async def list_filtered(
        self,
        organization_id: str,
        *,
        job_id: str | None = None,
        stage: CandidateStage | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> list[Candidate]:
        stmt = select(Candidate).where(Candidate.organization_id == organization_id)
        if job_id is not None:
            stmt = stmt.where(Candidate.job_id == job_id)
        if stage is not None:
            stmt = stmt.where(Candidate.stage == stage)
        if source is not None:
            stmt = stmt.where(Candidate.source == source)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(Candidate.full_name.ilike(like), Candidate.email.ilike(like)))
        stmt = stmt.order_by(Candidate.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
