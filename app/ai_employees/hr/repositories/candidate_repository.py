from __future__ import annotations

from typing import Literal

from sqlalchemy import func, or_, select

from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage
from app.shared.database.repository import OrgScopedRepository

CandidateVisibility = Literal["active", "archived", "all"]


class CandidateRepository(OrgScopedRepository[Candidate]):
    model = Candidate

    async def count_by_job(self, organization_id: str) -> dict[str, int]:
        """One GROUP BY query for every job's candidate count, rather than
        an N+1 count-per-job — used by JobService to populate
        JobResponse.candidate_count for a whole list at once. Archived
        candidates are excluded — the count reflects the active pipeline.
        """
        stmt = (
            select(Candidate.job_id, func.count(Candidate.id))
            .where(Candidate.organization_id == organization_id, Candidate.archived_at.is_(None))
            .group_by(Candidate.job_id)
        )
        result = await self.session.execute(stmt)
        return {job_id: count for job_id, count in result.all()}

    async def find_by_job_and_identity(
        self, organization_id: str, job_id: str, identity_id: str
    ) -> Candidate | None:
        """Used to make candidate creation from resume identity idempotent —
        a re-uploaded/duplicate resume for the same job+person reuses the
        existing Candidate (application) instead of creating a second one.
        Scoped by job_id so the same person applying to a *different* job
        correctly gets an independent Candidate row — see
        app.ai_employees.hr.services.candidate_identity.
        """
        stmt = select(Candidate).where(
            Candidate.organization_id == organization_id,
            Candidate.job_id == job_id,
            Candidate.identity_id == identity_id,
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
        visibility: CandidateVisibility = "active",
    ) -> list[Candidate]:
        stmt = select(Candidate).where(Candidate.organization_id == organization_id)
        if job_id is not None:
            stmt = stmt.where(Candidate.job_id == job_id)
        if stage is not None:
            stmt = stmt.where(Candidate.stage == stage)
        if source is not None:
            stmt = stmt.where(Candidate.source == source)
        if visibility == "active":
            stmt = stmt.where(Candidate.archived_at.is_(None))
        elif visibility == "archived":
            stmt = stmt.where(Candidate.archived_at.is_not(None))
        if search:
            like = f"%{search}%"
            stmt = stmt.join(
                CandidateIdentity, Candidate.identity_id == CandidateIdentity.id
            ).where(
                or_(CandidateIdentity.full_name.ilike(like), CandidateIdentity.email.ilike(like))
            )
        stmt = stmt.order_by(Candidate.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ids(self, organization_id: str, ids: list[str]) -> list[Candidate]:
        if not ids:
            return []
        stmt = select(Candidate).where(
            Candidate.organization_id == organization_id, Candidate.id.in_(ids)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
