"""Keyset pagination helper.

Because every primary key is a ULID (lexicographically sortable by creation
time, see ``app.shared.database.ids``), the row ID itself is a valid keyset
cursor — no separate offset bookkeeping needed.
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import ColumnElement, Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.pagination.schemas import Paginated

RowT = TypeVar("RowT")


async def paginate(
    session: AsyncSession,
    stmt: Select,
    *,
    id_column: ColumnElement,
    cursor: str | None,
    page_size: int,
) -> tuple[list, str | None, bool]:
    """Apply a keyset cursor + limit to ``stmt`` (must already be ordered by id_column desc)."""
    if cursor:
        stmt = stmt.where(id_column < cursor)
    stmt = stmt.limit(page_size + 1)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    next_cursor: str | None = None
    if has_more and rows and id_column.key is not None:
        next_cursor = getattr(rows[-1], id_column.key)
    return rows, next_cursor, has_more


def to_paginated(
    items: list, next_cursor: str | None, has_more: bool, total: int | None = None
) -> Paginated[Any]:
    return Paginated(items=items, next_cursor=next_cursor, has_more=has_more, total=total)
