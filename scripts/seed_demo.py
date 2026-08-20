"""Seed script for demo@aivra-demo.com and sample candidate in SCREENING_APPROVED stage.

Usage: python scripts/seed_demo.py
"""

import asyncio
from datetime import datetime, UTC, timedelta
from sqlalchemy import select

from app.shared.database.session import get_session_factory
from app.shared.security.passwords import hash_password
from app.shared.rbac.roles import OrgRole
from app.identity.models.user import User
from app.organizations.models.organization import Organization
from app.organizations.models.membership import OrganizationMember, MembershipStatus
from app.ai_employees.provisioning.models.provision import EmployeeProvision, ProvisionStatus
from app.ai_employees.registry.models.catalog import AIEmployeeType, EmployeeTypeCode, CommercialModel
from app.ai_employees.hr.models.job import HrJob, EmploymentType, JobStatus
from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity, CandidateStage, CandidateSource
from app.ai_employees.hr.models.screening import Screening, ScreeningStatus
from app.ai_employees.hr.models.schedule_slot import ScheduleSlot

async def seed_demo():
    session_factory = get_session_factory()
    async with session_factory() as session:
        # 1. Seed or update Demo User
        user_res = await session.execute(select(User).where(User.email == "demo@aivra-demo.com"))
        user = user_res.scalar_one_or_none()
        if user is None:
            user = User(
                email="demo@aivra-demo.com",
                password_hash=hash_password("demo1234"),
                full_name="HR Demo Admin",
                is_active=True
            )
            session.add(user)
            await session.flush()
            print("Created user demo@aivra-demo.com")
        else:
            user.password_hash = hash_password("demo1234")
            user.is_active = True
            user.failed_login_attempts = 0
            user.locked_until = None
            await session.flush()

        # 2. Seed or get Organization
        org_res = await session.execute(select(Organization).where(Organization.slug == "aivra-demo"))
        org = org_res.scalar_one_or_none()
        if org is None:
            org = Organization(
                name="Acme Corporation",
                slug="aivra-demo",
                created_by_user_id=user.id
            )
            session.add(org)
            await session.flush()

        # 3. Seed Membership
        mem_res = await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.user_id == user.id
            )
        )
        mem = mem_res.scalar_one_or_none()
        if mem is None:
            mem = OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=OrgRole.OWNER,
                status=MembershipStatus.ACTIVE
            )
            session.add(mem)
            await session.flush()

        # 4. Seed HR Provision
        hr_type_res = await session.execute(select(AIEmployeeType).where(AIEmployeeType.code == EmployeeTypeCode.HR))
        hr_type = hr_type_res.scalar_one_or_none()
        if hr_type is None:
            hr_type = AIEmployeeType(
                code=EmployeeTypeCode.HR,
                name="AI HR Employee",
                description="Recruiting automation",
                commercial_model=CommercialModel.SELF_SERVICE_SUBSCRIPTION
            )
            session.add(hr_type)
            await session.flush()

        prov_res = await session.execute(
            select(EmployeeProvision).where(
                EmployeeProvision.organization_id == org.id,
                EmployeeProvision.employee_type_id == hr_type.id
            )
        )
        if prov_res.scalar_one_or_none() is None:
            session.add(EmployeeProvision(
                organization_id=org.id,
                employee_type_id=hr_type.id,
                status=ProvisionStatus.ACTIVE
            ))
            await session.flush()

        # 5. Seed Job
        job_res = await session.execute(
            select(HrJob).where(
                HrJob.organization_id == org.id,
                HrJob.title == "Senior Full Stack Engineer"
            )
        )
        job = job_res.scalar_one_or_none()
        if job is None:
            job = HrJob(
                organization_id=org.id,
                created_by_user_id=user.id,
                title="Senior Full Stack Engineer",
                company_name="Acme Corporation",
                department="Engineering",
                location="Bengaluru, India",
                employment_type=EmploymentType.FULL_TIME,
                status=JobStatus.OPEN,
                description="Looking for an experienced Full Stack Engineer with strong Python and React skills.",
                requirements=["Python", "React", "PostgreSQL", "FastAPI"]
            )
            session.add(job)
            await session.flush()

        # 6. Seed Candidate Identity
        ident_res = await session.execute(
            select(CandidateIdentity).where(
                CandidateIdentity.organization_id == org.id,
                CandidateIdentity.email == "alex.rivera@example.com"
            )
        )
        identity = ident_res.scalar_one_or_none()
        if identity is None:
            identity = CandidateIdentity(
                organization_id=org.id,
                full_name="Alex Rivera",
                email="alex.rivera@example.com",
                phone="+919876543210"
            )
            session.add(identity)
            await session.flush()

        # 7. Seed Candidate Application
        cand_res = await session.execute(
            select(Candidate).where(
                Candidate.organization_id == org.id,
                Candidate.job_id == job.id,
                Candidate.identity_id == identity.id
            )
        )
        candidate = cand_res.scalar_one_or_none()
        if candidate is None:
            candidate = Candidate(
                organization_id=org.id,
                job_id=job.id,
                identity_id=identity.id,
                source=CandidateSource.RESUME_UPLOAD,
                stage=CandidateStage.SCREENING_APPROVED
            )
            session.add(candidate)
            await session.flush()
        else:
            candidate.stage = CandidateStage.SCREENING_APPROVED
            await session.flush()

        # 8. Seed Screening Record with Prompt and Reset to PENDING
        screen_res = await session.execute(
            select(Screening).where(
                Screening.organization_id == org.id,
                Screening.candidate_id == candidate.id
            )
        )
        screening = screen_res.scalar_one_or_none()
        prompt_text = (
            "## AI Screening Prompt for Alex Rivera\n"
            "Position: Senior Full Stack Engineer at Acme Corporation\n\n"
            "Objective:\n"
            "Evaluate candidate's technical experience with Python, FastAPI, and React, "
            "as well as their availability and CTC expectations.\n\n"
            "Screening Instructions:\n"
            "1. Introduction: Greet Alex Rivera on behalf of Acme Corporation.\n"
            "2. Experience Check: Ask about recent projects built with Python and React.\n"
            "3. System Design: Ask how Alex handles scalable backend architectures.\n"
            "4. Operational Fit: Verify current CTC, expected CTC, and notice period.\n"
            "5. Closing: Thank candidate and explain next steps."
        )
        if screening is None:
            screening = Screening(
                organization_id=org.id,
                candidate_id=candidate.id,
                status=ScreeningStatus.PENDING,
                prompt_text=prompt_text,
                prompt_generated_at=datetime.now(UTC)
            )
            session.add(screening)
            await session.flush()
        else:
            screening.status = ScreeningStatus.PENDING
            screening.prompt_text = prompt_text
            await session.flush()

        # 9. Seed Schedule Slots
        slot_res = await session.execute(
            select(ScheduleSlot).where(
                ScheduleSlot.organization_id == org.id,
                ScheduleSlot.interviewer_user_id == user.id
            )
        )
        slots = slot_res.scalars().all()
        if not slots:
            now = datetime.now(UTC)
            for i in range(1, 4):
                start_time = now + timedelta(days=i, hours=2)
                end_time = start_time + timedelta(hours=1)
                slot = ScheduleSlot(
                    organization_id=org.id,
                    interviewer_user_id=user.id,
                    start_time=start_time,
                    end_time=end_time,
                    is_booked=False
                )
                session.add(slot)
            await session.flush()

        await session.commit()
        print(f"SEED COMPLETE! Candidate ID: {candidate.id}")

if __name__ == "__main__":
    asyncio.run(seed_demo())
