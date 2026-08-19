"""Declarative base and reusable mixins for all bounded-context models.

``OrgScopedMixin`` is the multi-tenancy backbone (spec section 7): every
tenant-owned table includes it, and repositories built on top of
``app.shared.database.repository.OrgScopedRepository`` refuse to run a query
without an explicit organization_id filter.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class OrgScopedMixin(TimestampMixin):
    """Mixin for every tenant-owned table.

    ``organization_id`` has no default: callers must always supply it from
    server-side authenticated context, never from client input (spec 7/9).
    """

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
