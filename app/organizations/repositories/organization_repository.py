from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models.organization import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, organization_id: str) -> Organization | None:
        return await self.session.get(Organization, organization_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        await self.session.flush()
        return organization

    async def search_and_count(
        self, *, query: str | None, page: int, page_size: int
    ) -> tuple[list[Organization], int]:
        """Admin Customer Directory listing (Phase 5) — simple offset
        pagination matching the frontend's existing (previously unused)
        ``Paginated<T>`` shape (page/pageSize/total), rather than the
        keyset-cursor helper in app.shared.pagination: an admin table with
        a search box and page numbers is a better fit for offset paging
        than infinite-scroll cursors.
        """
        filters = []
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(or_(Organization.name.ilike(pattern), Organization.slug.ilike(pattern)))

        count_stmt = select(func.count()).select_from(Organization)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = select(Organization).order_by(Organization.created_at.desc())
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total
