import asyncio
from sqlalchemy import select
from app.shared.database.session import get_session_factory
from app.ai_employees.hr.models.screening import Screening

async def main():
    f = get_session_factory()
    async with f() as s:
        res = await s.execute(select(Screening).where(Screening.candidate_id == 'cand_01m0f2ke9zffn79pem3jpsckwf'))
        scr = res.scalars().all()
        print(f"Found {len(scr)} screenings for cand_01m0f2ke9zffn79pem3jpsckwf:")
        for s_row in scr:
            print(f" - ID: {s_row.id}, Status: {s_row.status}, Prompt length: {len(s_row.prompt_text or '')}")

if __name__ == "__main__":
    asyncio.run(main())
