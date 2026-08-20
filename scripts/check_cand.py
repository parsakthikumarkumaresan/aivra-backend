import asyncio
from sqlalchemy import select
from app.shared.database.session import get_session_factory
from app.ai_employees.hr.models.candidate import Candidate
from app.organizations.models.organization import Organization

async def main():
    f = get_session_factory()
    async with f() as s:
        res = await s.execute(select(Candidate).where(Candidate.id == 'cand_01m0f2ke9zffn79pem3jpsckwf'))
        c = res.scalar_one_or_none()
        if c:
            print(f"Candidate ID: {c.id}, Org ID: {c.organization_id}, Stage: {c.stage}")
            org_res = await s.execute(select(Organization).where(Organization.id == c.organization_id))
            org = org_res.scalar_one_or_none()
            if org:
                print(f"Org Name: {org.name}, Org Slug: {org.slug}")

if __name__ == "__main__":
    asyncio.run(main())
