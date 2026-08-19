from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, TimestampMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column
from app.shared.rbac.roles import OrgRole


class MembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    REMOVED = "removed"


class OrganizationMember(Base, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member_org_user"),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.MEMBERSHIP)
    )
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[OrgRole] = mapped_column(str_enum_column(OrgRole, 30), nullable=False)
    status: Mapped[MembershipStatus] = mapped_column(
        str_enum_column(MembershipStatus, 20), default=MembershipStatus.ACTIVE, nullable=False
    )
    invited_by_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
