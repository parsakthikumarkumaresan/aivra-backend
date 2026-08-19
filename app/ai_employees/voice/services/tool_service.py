from __future__ import annotations

from app.ai_employees.voice.models.tool import Tool, ToolAuthType, ToolKind, ToolMethod
from app.ai_employees.voice.repositories.tool_repository import ToolRepository
from app.shared.errors.exceptions import NotFoundError, ValidationAppError


class ToolService:
    def __init__(self, tool_repo: ToolRepository) -> None:
        self.tool_repo = tool_repo

    async def list_tools(self, organization_id: str) -> list[Tool]:
        return await self.tool_repo.list_for_organization(organization_id)

    async def get_tool(self, organization_id: str, tool_id: str) -> Tool:
        tool = await self.tool_repo.get_by_id(organization_id, tool_id)
        if tool is None:
            raise NotFoundError("Tool not found.")
        return tool

    async def create_tool(
        self,
        *,
        organization_id: str,
        name: str,
        kind: ToolKind,
        endpoint: str,
        description: str | None = None,
        method: ToolMethod = ToolMethod.POST,
        auth_type: ToolAuthType = ToolAuthType.NONE,
        credential_ref: str | None = None,
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        timeout_ms: int = 10_000,
        retry_policy: dict | None = None,
    ) -> Tool:
        if kind == ToolKind.API and not endpoint.startswith(("http://", "https://")):
            raise ValidationAppError("API tools must have a valid http or https endpoint URL.")

        tool = Tool(
            organization_id=organization_id,
            name=name,
            description=description,
            kind=kind,
            method=method,
            endpoint=endpoint,
            auth_type=auth_type,
            credential_ref=credential_ref,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            timeout_ms=timeout_ms,
            retry_policy=retry_policy or {"max_attempts": 2, "backoff_ms": 500},
            enabled=True,
        )
        return await self.tool_repo.add(tool)

    async def update_tool(
        self,
        organization_id: str,
        tool_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        endpoint: str | None = None,
        method: ToolMethod | None = None,
        auth_type: ToolAuthType | None = None,
        credential_ref: str | None = None,
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        timeout_ms: int | None = None,
        retry_policy: dict | None = None,
        enabled: bool | None = None,
    ) -> Tool:
        tool = await self.get_tool(organization_id, tool_id)
        if name is not None:
            tool.name = name
        if description is not None:
            tool.description = description
        if endpoint is not None:
            if tool.kind == ToolKind.API and not endpoint.startswith(("http://", "https://")):
                raise ValidationAppError("API tools must have a valid http or https endpoint URL.")
            tool.endpoint = endpoint
        if method is not None:
            tool.method = method
        if auth_type is not None:
            tool.auth_type = auth_type
        if credential_ref is not None:
            tool.credential_ref = credential_ref
        if input_schema is not None:
            tool.input_schema = input_schema
        if output_schema is not None:
            tool.output_schema = output_schema
        if timeout_ms is not None:
            tool.timeout_ms = timeout_ms
        if retry_policy is not None:
            tool.retry_policy = retry_policy
        if enabled is not None:
            tool.enabled = enabled
        tool.version += 1
        return tool

    async def toggle_tool(self, organization_id: str, tool_id: str, *, enabled: bool) -> Tool:
        tool = await self.get_tool(organization_id, tool_id)
        tool.enabled = enabled
        return tool
