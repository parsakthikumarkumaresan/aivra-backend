from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.hr.api.dependencies import require_hr_active, require_hr_role
from app.ai_employees.hr.repositories.assessment_repository import AssessmentRepository
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.job_repository import JobRepository
from app.ai_employees.hr.repositories.processing_job_repository import ProcessingJobRepository
from app.ai_employees.hr.repositories.resume_repository import ResumeRepository
from app.ai_employees.hr.schemas.assessment import AssessmentResponse
from app.ai_employees.hr.schemas.candidate import CandidateResponse
from app.ai_employees.hr.schemas.resume import (
    ProcessingJobResponse,
    ResumeResponse,
    UploadResumeResponse,
)
from app.ai_employees.hr.services.resume_service import ResumeService
from app.shared.database.session import get_db
from app.shared.errors.exceptions import NotFoundError
from app.shared.rbac.roles import HR_OPERATOR_ROLES
from app.shared.security.dependencies import AuthContext
from app.shared.storage.factory import StorageCategory, get_object_storage
from app.workers.jobs.hr_resume_jobs import enqueue_resume_processing

router = APIRouter(prefix="/hr/resumes", tags=["hr-resumes"])


def _service(db: AsyncSession = Depends(get_db)) -> ResumeService:
    return ResumeService(
        ResumeRepository(db),
        CandidateRepository(db),
        JobRepository(db),
        ProcessingJobRepository(db),
        get_object_storage(StorageCategory.DOCUMENTS),
    )


@router.post("", response_model=UploadResumeResponse, status_code=201)
async def upload_resume(
    background_tasks: BackgroundTasks,
    job_id: str = Form(...),
    candidate_name: str = Form(...),
    candidate_email: str = Form(...),
    candidate_phone: str | None = Form(None),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_hr_role(*HR_OPERATOR_ROLES)),
    service: ResumeService = Depends(_service),
) -> UploadResumeResponse:
    content = await file.read()
    candidate, resume, processing_job = await service.upload_resume(
        organization_id=auth.require_organization_id(),
        job_id=job_id,
        filename=file.filename or "resume.pdf",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        candidate_phone=candidate_phone,
    )

    # Enqueued via BackgroundTasks (runs after the response — and after the
    # request's DB commit — completes) so the worker never races the commit
    # that makes this Resume row visible.
    background_tasks.add_task(
        enqueue_resume_processing,
        organization_id=auth.require_organization_id(),
        resume_id=resume.id,
    )

    return UploadResumeResponse(
        candidate=CandidateResponse.model_validate(candidate),
        resume=ResumeResponse.model_validate(resume),
        processing_job=ProcessingJobResponse.model_validate(processing_job),
    )


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    auth: AuthContext = Depends(require_hr_active),
    db: AsyncSession = Depends(get_db),
) -> ResumeResponse:
    resume = await ResumeRepository(db).get_by_id(auth.require_organization_id(), resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    return ResumeResponse.model_validate(resume)


@router.get("/candidates/{candidate_id}/assessment", response_model=AssessmentResponse)
async def get_candidate_assessment(
    candidate_id: str,
    auth: AuthContext = Depends(require_hr_active),
    db: AsyncSession = Depends(get_db),
) -> AssessmentResponse:
    assessment = await AssessmentRepository(db).get_latest_for_candidate(
        auth.require_organization_id(), candidate_id
    )
    if assessment is None:
        raise NotFoundError("No assessment exists for this candidate yet.")
    return AssessmentResponse.model_validate(assessment)
