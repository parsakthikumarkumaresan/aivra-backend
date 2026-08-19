"""Cursor-based pagination shared across all list endpoints (spec section 18).

Mirrors the frontend's currently-unused ``Paginated<T>`` type
(``src/types/common.ts``) so wiring real pagination into list calls later is
additive, not a contract break.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field

from app.shared.schemas.base import CamelModel

ItemT = TypeVar("ItemT")


class PageParams(CamelModel):
    cursor: str | None = None
    page_size: int = Field(default=20, ge=1, le=100)


class Paginated(CamelModel, Generic[ItemT]):
    items: list[ItemT]
    next_cursor: str | None = None
    has_more: bool = False
    total: int | None = None
