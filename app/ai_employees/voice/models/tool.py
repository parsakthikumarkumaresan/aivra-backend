from __future__ import annotations

from enum import StrEnum

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class ToolKind(StrEnum):
    API = "api"
    TRANSFER = "transfer"
    INTERNAL = "internal"


class ToolAuthType(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"


class ToolMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class Tool(Base, OrgScopedMixin):
    """ToolDefinition (spec section 13). Organization-scoped and reusable
    across multiple VoiceAgents — an AgentVersion references tools by ID
    (``tool_ids`` in its config), it never embeds a copy.
    """

    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.TOOL)
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    kind: Mapped[ToolKind] = mapped_column(str_enum_column(ToolKind, 20), nullable=False)
    method: Mapped[ToolMethod] = mapped_column(
        str_enum_column(ToolMethod, 10), default=ToolMethod.POST, nullable=False
    )
    # "internal://..." pseudo-URL for kind=internal (e.g. call transfer),
    # a real HTTPS endpoint for kind=api.
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_type: Mapped[ToolAuthType] = mapped_column(
        str_enum_column(ToolAuthType, 20), default=ToolAuthType.NONE, nullable=False
    )
    # Opaque reference to a secret held elsewhere — never the raw credential
    # (spec section 13: "never expose secrets to the model").
    credential_ref: Mapped[str | None] = mapped_column(String(255))
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=10_000, nullable=False)
    retry_policy: Mapped[dict] = mapped_column(
        JSON, default=lambda: {"max_attempts": 2, "backoff_ms": 500}, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
