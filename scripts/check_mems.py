import asyncio
from sqlalchemy import select
from app.shared.database.session import get_session_factory
from app.identity.models.user import User
from app.organizations.models.membership import OrganizationMember

async def main():
    f = get_session_factory()
    async with f() as s:
        user_res = await s.execute(select(User).where(User.email == "demo@aivra-demo.com"))
        user = user_res.scalar_one_or_none()
        if user:
            mem_res = await s.execute(select(OrganizationMember).where(OrganizationMember.user_id == user.id))
            mems = mem_res.scalars().all()
            print(f"User {user.email} (ID: {user.id}) has {len(mems)} memberships:")
            for m in mems:
                print(f" - Org ID: {m.organization_id}, Role: {m.role}, Status: {m.status}")

if __name__ == "__main__":
    asyncio.run(main())
