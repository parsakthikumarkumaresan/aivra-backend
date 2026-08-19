"""Seed the AI Employee catalog (HR, Voice) and HR's purchasable plans.

Idempotent — safe to run repeatedly in any environment (local/staging/prod
bootstrap). Voice has no self-service Plan rows: it is managed/custom
(spec section 17), so only HR gets purchasable plans here.

Usage: python scripts/seed_catalog.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_employees.registry.models.catalog import (
    AIEmployeeType,
    CommercialModel,
    EmployeeCatalogItem,
    EmployeeTypeCode,
)
from app.core.config import get_settings
from app.shared.database.session import get_session_factory
from app.subscriptions.models.plan import BillingCycle, Plan


async def _get_or_create_employee_type(
    session: AsyncSession,
    code: EmployeeTypeCode,
    name: str,
    description: str,
    model: CommercialModel,
) -> AIEmployeeType:
    result = await session.execute(select(AIEmployeeType).where(AIEmployeeType.code == code))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    employee_type = AIEmployeeType(
        code=code, name=name, description=description, commercial_model=model
    )
    session.add(employee_type)
    await session.flush()
    return employee_type


async def _get_or_create_catalog_item(
    session: AsyncSession, employee_type: AIEmployeeType, name: str, tagline: str, description: str
) -> EmployeeCatalogItem:
    result = await session.execute(
        select(EmployeeCatalogItem).where(EmployeeCatalogItem.employee_type_id == employee_type.id)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    item = EmployeeCatalogItem(
        employee_type_id=employee_type.id,
        name=name,
        tagline=tagline,
        description=description,
        base_price_monthly=99.00,
    )
    session.add(item)
    await session.flush()
    return item


async def _get_or_create_plan(
    session: AsyncSession,
    employee_type: AIEmployeeType,
    code: str,
    name: str,
    billing_cycle: BillingCycle,
    price: float,
) -> Plan:
    result = await session.execute(select(Plan).where(Plan.code == code))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    plan = Plan(
        employee_type_id=employee_type.id,
        code=code,
        name=name,
        billing_cycle=billing_cycle,
        price=price,
        # external_price_id is intentionally left unset until a real Stripe
        # account is configured — see docs/adr/0001-payment-provider.md.
    )
    session.add(plan)
    await session.flush()
    return plan


async def seed() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        hr = await _get_or_create_employee_type(
            session,
            EmployeeTypeCode.HR,
            "AI HR Employee",
            "Recruiting, screening and interview automation.",
            CommercialModel.SELF_SERVICE_SUBSCRIPTION,
        )
        voice = await _get_or_create_employee_type(
            session,
            EmployeeTypeCode.VOICE,
            "AI Voice Employee",
            "Custom voice agent for calls, support and lead qualification.",
            CommercialModel.MANAGED_CUSTOM,
        )

        await _get_or_create_catalog_item(
            session,
            hr,
            "AI HR Employee",
            "Hire smarter, faster.",
            "Full recruiting pipeline automation.",
        )
        await _get_or_create_catalog_item(
            session,
            voice,
            "AI Voice Employee",
            "Custom voice, deployed by AIVRA.",
            "Managed voice agent.",
        )

        await _get_or_create_plan(
            session, hr, "hr_standard_monthly", "HR Standard", BillingCycle.MONTHLY, 99.00
        )
        await _get_or_create_plan(
            session, hr, "hr_standard_annual", "HR Standard (Annual)", BillingCycle.ANNUAL, 999.00
        )

        await session.commit()
    print(f"Seeded catalog against {get_settings().database_url}")


if __name__ == "__main__":
    asyncio.run(seed())
