import asyncio
from sqlalchemy import select
from app.shared.database.session import get_session_factory
from app.identity.models.user import User
from app.organizations.models.membership import OrganizationMember
from app.ai_employees.hr.models.candidate import Candidate
from app.identity.models.session import Session

async def main():
    f = get_session_factory()
    async with f() as s:
        user_res = await s.execute(select(User).where(User.email == "demo@aivra-demo.com"))
        user = user_res.scalar_one_or_none()
        
        c_res = await s.execute(select(Candidate).where(Candidate.id == "cand_01m0f2ke9zffn79pem3jpsckwf"))
        c = c_res.scalar_one_or_none()
        
        s_res = await s.execute(select(Session).where(Session.user_id == user.id))
        sessions = s_res.scalars().all()
        
        print(f"Candidate ID: {c.id}, Candidate Org ID: {c.organization_id}")
        print(f"User Active Sessions count: {len(sessions)}")
        for sess in sessions:
            print(f" Session ID: {sess.id}, Session Org ID: {sess.organization_id}")

if __name__ == "__main__":
    asyncio.run(main())
