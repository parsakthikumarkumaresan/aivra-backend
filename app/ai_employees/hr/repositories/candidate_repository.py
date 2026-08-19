from __future__ import annotations

from sqlalchemy import func, or_, select

from app.ai_employees.hr.models.candidate import Candidate, CandidateStage
from app.shared.database.repository import OrgScopedRepository


class CandidateRepository(OrgScopedRepository[Candidate]):
    model = Candidate

    async def count_by_job(self, organization_id: str) -> dict[str, int]:
        """One GROUP BY query for every job's candidate count, rather than
        an N+1 count-per-job — used by JobService to populate
        JobResponse.candidate_count for a whole list at once.
        """
        stmt = (
            select(Candidate.job_id, func.count(Candidate.id))
            .where(Candidate.organization_id == organization_id)
            .group_by(Candidate.job_id)
        )
        result = await self.session.execute(stmt)
        return {job_id: count for job_id, count in result.all()}

    async def find_by_job_and_email(
        self, organization_id: str, job_id: str, email: str
    ) -> Candidate | None:
        """Used to make candidate creation from resume identity idempotent —
        a re-uploaded/duplicate resume for the same job+person reuses the
        existing Candidate instead of creating a second one.
        """
        stmt = select(Candidate).where(
            Candidate.organization_id == organization_id,
            Candidate.job_id == job_id,
            Candidate.email == email,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

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
