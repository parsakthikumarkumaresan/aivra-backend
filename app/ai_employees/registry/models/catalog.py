from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class EmployeeTypeCode(StrEnum):
    """The two AI Employees in the first release (spec section 2)."""

    HR = "hr"
    VOICE = "voice"


class CommercialModel(StrEnum):
    """HR is self-service subscription; Voice is AIVRA-managed/custom (spec section 17)."""

    SELF_SERVICE_SUBSCRIPTION = "self_service_subscription"
    MANAGED_CUSTOM = "managed_custom"


class AIEmployeeType(Base, TimestampMixin):
    """Definition of an AI Employee product (HR or Voice)."""

    __tablename__ = "ai_employee_types"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.AI_EMPLOYEE_TYPE)
    )
    code: Mapped[EmployeeTypeCode] = mapped_column(
        str_enum_column(EmployeeTypeCode, 30), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    commercial_model: Mapped[CommercialModel] = mapped_column(
        str_enum_column(CommercialModel, 40), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EmployeeCatalogItem(Base, TimestampMixin):
    """Public commercial metadata for an employee type (pricing/plan display)."""

    __tablename__ = "employee_catalog_items"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CATALOG_ITEM)
    )
    employee_type_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("ai_employee_types.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tagline: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    base_price_monthly: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
