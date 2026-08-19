"""Request-scoped context: correlation ID generation/propagation.

Actor/organization context is set directly by
``app.shared.security.dependencies.get_auth_context`` once authentication
resolves (not here) — that dependency runs during ``call_next``, so setting
it in this middleware would only ever apply after the request already
finished.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.logging import request_id_ctx


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        incoming_id = request.headers.get(settings.request_id_header)
        request_id = incoming_id or f"req_{uuid.uuid4().hex}"

        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)

        response.headers[settings.request_id_header] = request_id
        return response
