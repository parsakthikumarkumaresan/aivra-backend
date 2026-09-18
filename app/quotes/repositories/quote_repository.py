from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.quotes.models.quote import Quote, QuoteStatus


class QuoteRepository:
    """Persistence operations for Quotes and QuoteLineItems."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, quote: Quote) -> Quote:
        self.session.add(quote)
        await self.session.flush()
        return quote

    async def get_by_id(self, quote_id: str) -> Quote | None:
        stmt = select(Quote).where(Quote.id == quote_id).options(selectinload(Quote.line_items))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_quote_number(self, quote_number: str) -> Quote | None:
        stmt = (
            select(Quote)
            .where(Quote.quote_number == quote_number)
            .options(selectinload(Quote.line_items))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def search_and_count(
        self,
        *,
        organization_id: str | None = None,
        lead_id: str | None = None,
        voice_project_id: str | None = None,
        status: QuoteStatus | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Quote], int]:
        stmt = select(Quote).options(selectinload(Quote.line_items))
        count_stmt = select(func.count(Quote.id))

        if organization_id:
            stmt = stmt.where(Quote.organization_id == organization_id)
            count_stmt = count_stmt.where(Quote.organization_id == organization_id)

        if lead_id:
            stmt = stmt.where(Quote.lead_id == lead_id)
            count_stmt = count_stmt.where(Quote.lead_id == lead_id)

        if voice_project_id:
            stmt = stmt.where(Quote.voice_project_id == voice_project_id)
            count_stmt = count_stmt.where(Quote.voice_project_id == voice_project_id)

        if status:
            stmt = stmt.where(Quote.status == status)
            count_stmt = count_stmt.where(Quote.status == status)

        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(Quote.quote_number.ilike(term) | Quote.title.ilike(term))
            count_stmt = count_stmt.where(Quote.quote_number.ilike(term) | Quote.title.ilike(term))

        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = stmt.order_by(desc(Quote.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        items_res = await self.session.execute(stmt)
        quotes = list(items_res.scalars().all())

        return quotes, total

    async def generate_next_quote_number(self, year: int | None = None) -> str:
        """Generates a sequential human-readable quote number: JEXA-Q-YYYY-NNNN."""
        if year is None:
            year = datetime.now(UTC).year

        prefix = f"JEXA-Q-{year}-"
        pattern = f"{prefix}%"

        stmt = (
            select(Quote.quote_number)
            .where(Quote.quote_number.like(pattern))
            .order_by(desc(Quote.quote_number))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        latest = result.scalar()

        if not latest:
            return f"{prefix}0001"

        try:
            suffix = latest.replace(prefix, "")
            seq = int(suffix) + 1
            return f"{prefix}{seq:04d}"
        except ValueError:
            # Fallback if any custom suffix exists
            count_stmt = select(func.count(Quote.id)).where(Quote.quote_number.like(pattern))
            count = (await self.session.execute(count_stmt)).scalar() or 0
            return f"{prefix}{count + 1:04d}"
