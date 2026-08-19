from __future__ import annotations

from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class ActorType(StrEnum):
    """Spec section 38."""

    USER = "user"
    AIVRA_ADMIN = "aivra_admin"
    SYSTEM = "system"


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditEvent(Base, OrgScopedMixin):
    """Immutable business/security audit trail (spec section 38) — kept
    separate from ordinary structured application logs (spec section 25).
    Only ever inserted, never updated or deleted by application code.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.AUDIT_EVENT)
    )
    actor_id: Mapped[str | None] = mapped_column(String(40))
    actor_type: Mapped[ActorType] = mapped_column(str_enum_column(ActorType, 20), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(60), nullable=False)
    result: Mapped[AuditResult] = mapped_column(
        str_enum_column(AuditResult, 20), default=AuditResult.SUCCESS, nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(60))
