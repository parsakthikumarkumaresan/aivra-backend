"""Seed 4 demo customer accounts, each in their own organization, to exercise
every AI Employee subscription state from the user's perspective:

  user1 — both Jexa HR and Jaan (Voice) active
  user2 — only Jexa HR active
  user3 — only Jaan (Voice) active
  user4 — fresh signup, nothing purchased yet

The org `slug` for each is what the frontend keys off of (see
services/mock/data/subscriptions.ts -> DEMO_ORG_SCENARIO_MAP) to
automatically show the matching mock subscription state on login — no manual
"Developer" scenario switch needed. That mock layer only drives dashboard/
card display though — real API routes (HR jobs/candidates, Voice) are gated
by the actual EmployeeProvision row in Postgres (require_employee_active,
spec section 8), which the frontend's mock scenario has no power over. This
script sets that real provision to ACTIVE for `active_employee_types` on
each org, mirroring the two-step NOT_PROVISIONED -> PENDING_ACTIVATION ->
ACTIVE transition webhooks normally drive, so the real HR/Voice endpoints
actually work for these accounts instead of 403ing.

Usage: python scripts/seed_demo_users.py
"""

import asyncio

from sqlalchemy import select

from app.ai_employees.hr.models.job import EmploymentType, HrJob, JobStatus
from app.ai_employees.provisioning.models.provision import ProvisionStatus
from app.ai_employees.provisioning.repositories.provision_repository import ProvisionRepository
from app.ai_employees.provisioning.services.provisioning_service import ProvisioningService
from app.ai_employees.registry.models.catalog import EmployeeTypeCode
from app.ai_employees.registry.repositories.catalog_repository import CatalogRepository
from app.identity.models.user import User
from app.organizations.models.membership import MembershipStatus, OrganizationMember
from app.organizations.models.organization import Organization
from app.shared.database.session import get_session_factory
from app.shared.rbac.roles import OrgRole
from app.shared.security.passwords import hash_password

PASSWORD = "Demo@12345"

USERS = [
    {
        "email": "user1@jexa-demo.com",
        "full_name": "Ritika Sharma",
        "org_name": "Both AI Employees Co",
        "org_slug": "jaan-demo-both",
        "seed_hr_job": True,
        "active_employee_types": [EmployeeTypeCode.HR, EmployeeTypeCode.VOICE],
    },
    {
        "email": "user2@jexa-demo.com",
        "full_name": "Karthik Iyer",
        "org_name": "HR Only Co",
        "org_slug": "jaan-demo-hr",
        "seed_hr_job": True,
        "active_employee_types": [EmployeeTypeCode.HR],
    },
    {
        "email": "user3@jexa-demo.com",
        "full_name": "Meera Nair",
        "org_name": "Voice Only Co",
        "org_slug": "jaan-demo-voice",
        "seed_hr_job": False,
        "active_employee_types": [EmployeeTypeCode.VOICE],
    },
    {
        "email": "user4@jexa-demo.com",
        "full_name": "Arjun Verma",
        "org_name": "Fresh Signup Co",
        "org_slug": "jaan-demo-fresh",
        "seed_hr_job": False,
        "active_employee_types": [],
    },
    {
        # Local development/testing account (real voice engine
        # implementation pass) — both AI Employees ACTIVE via the same
        # real ProvisioningService state machine used above, not a
        # weakened/bypassed auth path. Local dev use only; this script is
        # never run against a production database.
        "email": "test1@gmail.com",
        "full_name": "Test Tester",
        "org_name": "Voice Engine Test Co",
        "org_slug": "voice-engine-test",
        "seed_hr_job": True,
        "active_employee_types": [EmployeeTypeCode.HR, EmployeeTypeCode.VOICE],
        "password": "12345",
    },
]


async def seed_demo_users():
    session_factory = get_session_factory()
    async with session_factory() as session:
        for spec in USERS:
            # 1. User — password defaults to the shared demo PASSWORD but
            # can be overridden per-entry (e.g. the local test1@gmail.com
            # account below), since real users may need a specific,
            # memorable credential rather than the shared demo one.
            password = spec.get("password", PASSWORD)
            user_res = await session.execute(select(User).where(User.email == spec["email"]))
            user = user_res.scalar_one_or_none()
            if user is None:
                user = User(
                    email=spec["email"],
                    password_hash=hash_password(password),
                    full_name=spec["full_name"],
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                print(f"Created user {spec['email']}")
            else:
                user.password_hash = hash_password(password)
                user.is_active = True
                user.failed_login_attempts = 0
                user.locked_until = None
                await session.flush()
                print(f"Updated user {spec['email']}")

            # 2. Organization
            org_res = await session.execute(select(Organization).where(Organization.slug == spec["org_slug"]))
            org = org_res.scalar_one_or_none()
            if org is None:
                org = Organization(
                    name=spec["org_name"],
                    slug=spec["org_slug"],
                )
                session.add(org)
                await session.flush()

            # 3. Membership
            mem_res = await session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org.id,
                    OrganizationMember.user_id == user.id,
                )
            )
            if mem_res.scalar_one_or_none() is None:
                session.add(
                    OrganizationMember(
                        organization_id=org.id,
                        user_id=user.id,
                        role=OrgRole.OWNER,
                        status=MembershipStatus.ACTIVE,
                    )
                )
                await session.flush()

            # 4. One sample HR job for orgs whose demo scenario has HR active,
            # so the real HR pages (jobs/candidates use the real backend, not
            # the mock layer) aren't empty when this user logs in.
            if spec["seed_hr_job"]:
                job_res = await session.execute(
                    select(HrJob).where(
                        HrJob.organization_id == org.id,
                        HrJob.title == "Senior Full Stack Engineer",
                    )
                )
                if job_res.scalar_one_or_none() is None:
                    session.add(
                        HrJob(
                            organization_id=org.id,
                            created_by_user_id=user.id,
                            title="Senior Full Stack Engineer",
                            company_name=spec["org_name"],
                            department="Engineering",
                            location="Bengaluru, India",
                            employment_type=EmploymentType.FULL_TIME,
                            status=JobStatus.OPEN,
                            description="Looking for an experienced Full Stack Engineer with strong Python and React skills.",
                            requirements=["Python", "React", "PostgreSQL", "FastAPI"],
                        )
                    )
                    await session.flush()

            # 5. Real entitlement — this is what actually gates the HR/Voice
            # API routes (require_employee_active), independent of the
            # frontend's mock subscription display.
            catalog_repo = CatalogRepository(session)
            provisioning = ProvisioningService(ProvisionRepository(session))
            for code in spec["active_employee_types"]:
                employee_type = await catalog_repo.get_employee_type_by_code(code)
                if employee_type is None:
                    print(f"  WARNING: no AI Employee type row for code={code!r} — run catalog seed first, skipping")
                    continue
                provision = await provisioning.get_or_create_not_provisioned(
                    organization_id=org.id, employee_type_id=employee_type.id
                )
                if provision.status == ProvisionStatus.NOT_PROVISIONED:
                    await provisioning.transition(
                        organization_id=org.id,
                        employee_type_id=employee_type.id,
                        target_status=ProvisionStatus.PENDING_ACTIVATION,
                        reason="Demo seed data",
                        actor_id=None,
                        actor_type="SYSTEM",
                    )
                if provision.status != ProvisionStatus.ACTIVE:
                    await provisioning.transition(
                        organization_id=org.id,
                        employee_type_id=employee_type.id,
                        target_status=ProvisionStatus.ACTIVE,
                        reason="Demo seed data",
                        actor_id=None,
                        actor_type="SYSTEM",
                    )
                await session.flush()

        await session.commit()
        print("\nSEED COMPLETE. Login with any of:")
        for spec in USERS:
            print(f"  {spec['email']}  /  {spec.get('password', PASSWORD)}")


if __name__ == "__main__":
    asyncio.run(seed_demo_users())
