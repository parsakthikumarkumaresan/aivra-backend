from __future__ import annotations

from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.shared.errors.exceptions import NotFoundError


class JobService:
    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

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

    async def list_jobs(self, organization_id: str) -> list[HrJob]:
        return await self.job_repo.list_for_organization(organization_id)

    async def get_job(self, organization_id: str, job_id: str) -> HrJob:
        job = await self.job_repo.get_by_id(organization_id, job_id)
        if job is None:
            raise NotFoundError("Job not found.")
        return job
