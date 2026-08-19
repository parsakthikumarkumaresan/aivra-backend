from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.models.job import EmploymentType
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.schemas.job import CreateJobRequest, JobResponse
from app.ai_employees.hr.services.job_service import JobService
from app.shared.database.session import get_db
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/hr/jobs", tags=["hr-jobs"])


def _service(db: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(JobRepository(db))


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    auth: AuthContext = Depends(require_hr_active), service: JobService = Depends(_service)
) -> list[JobResponse]:
    jobs = await service.list_jobs(auth.require_organization_id())
    return [JobResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    auth: AuthContext = Depends(require_hr_active),
    service: JobService = Depends(_service),
) -> JobResponse:
    job = await service.get_job(auth.require_organization_id(), job_id)
    return JobResponse.model_validate(job)


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    payload: CreateJobRequest,
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: JobService = Depends(_service),
) -> JobResponse:
    job = await service.create_job(
        organization_id=auth.require_organization_id(),
        created_by_user_id=auth.user.id,
        title=payload.title,
        department=payload.department,
        description=payload.description,
        requirements=payload.requirements,
        location=payload.location,
        employment_type=EmploymentType(payload.employment_type),
    )
    return JobResponse.model_validate(job)
