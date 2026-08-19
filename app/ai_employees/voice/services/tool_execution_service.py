from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.ai_employees.voice.models.tool import ToolAuthType, ToolKind, ToolMethod
from app.ai_employees.voice.models.tool_execution import ToolExecution, ToolExecutionStatus
from app.ai_employees.voice.repositories.tool_execution_repository import ToolExecutionRepository
from app.ai_employees.voice.repositories.tool_repository import ToolRepository
from app.shared.errors.exceptions import NotFoundError


class ToolExecutionService:
    def __init__(
        self,
        tool_repo: ToolRepository,
        execution_repo: ToolExecutionRepository,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.tool_repo = tool_repo
        self.execution_repo = execution_repo
        self._http_client = http_client

    async def execute_tool(
        self,
        organization_id: str,
        call_id: str,
        tool_id: str,
        input_data: dict[str, Any],
    ) -> ToolExecution:
        tool = await self.tool_repo.get_by_id(organization_id, tool_id)
        if tool is None:
            raise NotFoundError("Tool not found.")

        if not tool.enabled:
            execution = ToolExecution(
                organization_id=organization_id,
                call_id=call_id,
                tool_id=tool_id,
                input=input_data,
                output={"error": "Tool is disabled"},
                status=ToolExecutionStatus.FAILED,
                duration_ms=0,
                error_code="TOOL_DISABLED",
                timestamp=datetime.now(UTC),
            )
            return await self.execution_repo.add(execution)

        start_time = time.perf_counter()
        status = ToolExecutionStatus.SUCCESS
        error_code: str | None = None
        output: dict[str, Any] = {}

        if tool.kind == ToolKind.API:
            output, status, error_code = await self._execute_api_tool(tool, input_data)
        else:
            output = {
                "status": "success",
                "action": tool.endpoint,
                "input": input_data,
            }

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        execution = ToolExecution(
            organization_id=organization_id,
            call_id=call_id,
            tool_id=tool_id,
            input=input_data,
            output=output,
            status=status,
            duration_ms=elapsed_ms,
            error_code=error_code,
            timestamp=datetime.now(UTC),
        )
        return await self.execution_repo.add(execution)

    async def _execute_api_tool(
        self,
        tool: Any,
        input_data: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolExecutionStatus, str | None]:
        max_attempts = int(tool.retry_policy.get("max_attempts", 1)) if tool.retry_policy else 1
        backoff_ms = int(tool.retry_policy.get("backoff_ms", 500)) if tool.retry_policy else 500
        timeout_sec = float(tool.timeout_ms) / 1000.0

        headers: dict[str, str] = {}
        if tool.auth_type == ToolAuthType.BEARER and tool.credential_ref:
            headers["Authorization"] = f"Bearer {tool.credential_ref}"
        elif tool.auth_type == ToolAuthType.API_KEY and tool.credential_ref:
            headers["X-API-Key"] = tool.credential_ref

        client_provided = self._http_client is not None
        client = self._http_client or httpx.AsyncClient(timeout=timeout_sec)

        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    if tool.method == ToolMethod.GET:
                        response = await client.get(
                            tool.endpoint, params=input_data, headers=headers
                        )
                    elif tool.method == ToolMethod.PUT:
                        response = await client.put(tool.endpoint, json=input_data, headers=headers)
                    elif tool.method == ToolMethod.DELETE:
                        response = await client.delete(
                            tool.endpoint, params=input_data, headers=headers
                        )
                    else:
                        response = await client.post(
                            tool.endpoint, json=input_data, headers=headers
                        )

                    response.raise_for_status()
                    data = response.json() if response.content else {}
                    if not isinstance(data, dict):
                        data = {"result": data}
                    return data, ToolExecutionStatus.SUCCESS, None

                except httpx.TimeoutException:
                    if attempt == max_attempts:
                        return (
                            {"error": "Request timed out"},
                            ToolExecutionStatus.TIMEOUT,
                            "TIMEOUT",
                        )
                except httpx.HTTPStatusError as exc:
                    if attempt == max_attempts:
                        return (
                            {"error": str(exc), "status_code": exc.response.status_code},
                            ToolExecutionStatus.FAILED,
                            f"HTTP_{exc.response.status_code}",
                        )
                except Exception as exc:
                    if attempt == max_attempts:
                        return (
                            {"error": str(exc)},
                            ToolExecutionStatus.FAILED,
                            "EXECUTION_ERROR",
                        )

                if attempt < max_attempts:
                    await asyncio.sleep(backoff_ms / 1000.0)

            return (
                {"error": "Execution failed after retries"},
                ToolExecutionStatus.FAILED,
                "MAX_RETRIES_EXCEEDED",
            )
        finally:
            if not client_provided:
                await client.aclose()

    async def list_executions_for_call(
        self, organization_id: str, call_id: str
    ) -> list[ToolExecution]:
        return await self.execution_repo.list_for_call(organization_id, call_id)
