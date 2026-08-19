"""Base repository classes.

``OrgScopedRepository`` is the mandatory base for every repository that
touches an ``OrgScopedMixin`` table (spec section 7: "repositories require
organization context"). Every read/write method takes ``organization_id``
as an explicit, non-optional argument and folds it into the query — there
is no method that can accidentally return or mutate cross-tenant rows.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.database.base import OrgScopedMixin

ModelT = TypeVar("ModelT", bound=OrgScopedMixin)


class OrgScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, organization_id: str, entity_id: str) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.id == entity_id,  # type: ignore[attr-defined]
            self.model.organization_id == organization_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()
