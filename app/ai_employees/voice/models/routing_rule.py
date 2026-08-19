from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class RoutingCondition(StrEnum):
    BUSINESS_HOURS = "business_hours"
    AFTER_HOURS = "after_hours"
    REGION = "region"
    AGENT_UNAVAILABLE = "agent_unavailable"


class RoutingRule(Base, OrgScopedMixin):
    __tablename__ = "routing_rules"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.ROUTE)
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    condition: Mapped[RoutingCondition] = mapped_column(
        str_enum_column(RoutingCondition, 30), nullable=False
    )
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
