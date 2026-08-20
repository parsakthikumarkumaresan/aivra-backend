from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.models.job import EmploymentType, HrJob
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.schemas.job import CreateJobRequest, JobResponse
from app.ai_employees.hr.services.job_service import JobService
from app.shared.database.session import get_db
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext

router = APIRouter(prefix="/hr/jobs", tags=["hr-jobs"])


def _service(db: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(JobRepository(db), CandidateRepository(db))


def _to_response(job: HrJob, candidate_count: int) -> JobResponse:
    return JobResponse(
        id=job.id,
        title=job.title,
        company_name=job.company_name,
        ai_agent_name=job.ai_agent_name,
        department=job.department,
        description=job.description,
        requirements=job.requirements,
        location=job.location,
        employment_type=job.employment_type,
        status=job.status,
        created_at=job.created_at,
        candidate_count=candidate_count,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    auth: AuthContext = Depends(require_hr_active), service: JobService = Depends(_service)
) -> list[JobResponse]:
    jobs_with_counts = await service.list_jobs_with_candidate_counts(auth.require_organization_id())
    return [_to_response(job, count) for job, count in jobs_with_counts]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    auth: AuthContext = Depends(require_hr_active),
    service: JobService = Depends(_service),
) -> JobResponse:
    job, count = await service.get_job_with_candidate_count(auth.require_organization_id(), job_id)
    return _to_response(job, count)


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
        company_name=payload.company_name,
        ai_agent_name=payload.ai_agent_name,
        department=payload.department,
        description=payload.description,
        requirements=payload.requirements,
        location=payload.location,
        employment_type=EmploymentType(payload.employment_type),
    )
    return _to_response(job, candidate_count=0)
