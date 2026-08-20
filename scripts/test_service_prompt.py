import asyncio
from sqlalchemy import select
from app.shared.database.session import get_session_factory
from app.ai_employees.hr.repositories.screening_repository import ScreeningRepository
from app.ai_employees.hr.repositories.candidate_repository import CandidateRepository
from app.ai_employees.hr.repositories.candidate_identity_repository import CandidateIdentityRepository
from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.ai_employees.hr.services.screening_service import ScreeningService

async def main():
    f = get_session_factory()
    async with f() as s:
        svc = ScreeningService(
            ScreeningRepository(s),
            CandidateRepository(s),
            CandidateIdentityRepository(s),
            AuditService(AuditRepository(s))
        )
        try:
            res = await svc.get_or_generate_prompt("org_01m0ctnq7mq672yvrmk9skhqkd", "cand_01m0f2ke9zffn79pem3jpsckwf")
            print("Prompt success! Length:", len(res.prompt_text or ""))
        except Exception as e:
            print("Prompt exception type:", type(e))
            print("Prompt exception:", e)

if __name__ == "__main__":
    asyncio.run(main())
