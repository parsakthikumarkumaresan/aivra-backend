"""Base Pydantic model for every API request/response schema.

The frontend's TypeScript interfaces are camelCase; FastAPI/Python default
to snake_case. Rather than touch the frontend, every response schema
inherits from ``CamelModel`` so field aliases are generated automatically
(``organization_id`` <-> ``organizationId``) while the Python side keeps
idiomatic snake_case attribute names.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
