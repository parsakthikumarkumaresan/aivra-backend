from __future__ import annotations

from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.shared.errors.exceptions import NotFoundError


class JobService:
    def __init__(self, job_repo: JobRepository, candidate_repo: CandidateRepository) -> None:
        self.job_repo = job_repo
        self.candidate_repo = candidate_repo

    async def create_job(
        self,
        *,
        organization_id: str,
        created_by_user_id: str,
        title: str,
        department: str | None,
        description: str | None,
        requirements: list[str],
        location: str | None,
        employment_type: EmploymentType,
    ) -> HrJob:
        job = HrJob(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            title=title,
            department=department,
            description=description,
            requirements=requirements,
            location=location,
            employment_type=employment_type,
            status=JobStatus.OPEN,
        )
        return await self.job_repo.add(job)

    async def list_jobs_with_candidate_counts(
        self, organization_id: str
    ) -> list[tuple[HrJob, int]]:
        jobs = await self.job_repo.list_for_organization(organization_id)
        counts = await self.candidate_repo.count_by_job(organization_id)
        return [(job, counts.get(job.id, 0)) for job in jobs]

    async def get_job_with_candidate_count(
        self, organization_id: str, job_id: str
    ) -> tuple[HrJob, int]:
        job = await self.job_repo.get_by_id(organization_id, job_id)
        if job is None:
            raise NotFoundError("Job not found.")
        counts = await self.candidate_repo.count_by_job(organization_id)
        return job, counts.get(job.id, 0)
