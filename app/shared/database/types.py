"""Shared column type helper for Python ``StrEnum`` columns.

Plain ``mapped_column(String(N))`` with a ``Mapped[SomeEnum]`` annotation is
a type lie: SQLAlchemy returns the raw DB string at runtime, not an enum
instance, so ``.value``/enum equality breaks silently. This wraps
``sqlalchemy.Enum`` configured to store/read the enum's ``.value`` (not its
``.name``) as a plain VARCHAR + CHECK constraint, so the ORM actually gives
back real enum members while the column stays human-readable in the DB.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from sqlalchemy import Enum as SAEnum

EnumT = TypeVar("EnumT", bound=StrEnum)


def str_enum_column(enum_cls: type[EnumT], length: int) -> SAEnum:
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        validate_strings=True,
        create_constraint=True,
        values_callable=lambda obj: [member.value for member in obj],
    )
