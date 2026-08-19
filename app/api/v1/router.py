"""Top-level /api/v1 router. Each bounded context registers its own
sub-router here; this file only aggregates, it never contains route logic.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.ai_employees.hr.api.candidates import router as hr_candidates_router
from app.ai_employees.hr.api.interviews import router as hr_interviews_router
from app.ai_employees.hr.api.jobs import router as hr_jobs_router
from app.ai_employees.hr.api.resumes import router as hr_resumes_router
from app.ai_employees.hr.api.screenings import router as hr_screenings_router
from app.ai_employees.registry.api.employees import router as employees_router
from app.ai_employees.voice.api.analytics_routes import router as voice_analytics_router
from app.ai_employees.voice.api.builder_routes import router as voice_builder_router
from app.ai_employees.voice.api.customer_routes import router as voice_customer_router
from app.ai_employees.voice.api.telephony_routes import router as voice_telephony_router
from app.ai_employees.voice.api.webhook_routes import router as voice_webhook_router
from app.api.v1.health import router as health_router
from app.identity.api.auth import router as auth_router
from app.knowledge.api.sources import router as knowledge_router
from app.leads.api.leads import router as leads_router
from app.leads.api.voice_projects import router as voice_projects_router
from app.organizations.api.organizations import router as organizations_router
from app.subscriptions.api.subscriptions import billing_router
from app.subscriptions.api.subscriptions import router as subscriptions_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(organizations_router)
api_router.include_router(employees_router)
api_router.include_router(subscriptions_router)
api_router.include_router(billing_router)
api_router.include_router(leads_router)
api_router.include_router(voice_projects_router)
api_router.include_router(hr_jobs_router)
api_router.include_router(hr_candidates_router)
api_router.include_router(hr_resumes_router)
api_router.include_router(hr_screenings_router)
api_router.include_router(hr_interviews_router)
api_router.include_router(knowledge_router)
api_router.include_router(voice_builder_router)
api_router.include_router(voice_customer_router)
api_router.include_router(voice_analytics_router)
api_router.include_router(voice_telephony_router)
api_router.include_router(voice_webhook_router)
