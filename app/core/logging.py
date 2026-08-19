"""Structured logging configuration.

Produces JSON logs carrying request/correlation IDs (spec section 25/31).
Never log secrets, tokens, or raw PII — callers must pass already-redacted
fields. See app.shared.errors for how request_id flows into error responses.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

from app.core.config import get_settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
organization_id_ctx: ContextVar[str | None] = ContextVar("organization_id", default=None)
actor_id_ctx: ContextVar[str | None] = ContextVar("actor_id", default=None)

_REDACTED_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "api_key",
    "credit_card",
}


def _redact_sensitive(_logger: object, _method_name: str, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACTED_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def _inject_context(_logger: object, _method_name: str, event_dict: dict) -> dict:
    request_id = request_id_ctx.get()
    organization_id = organization_id_ctx.get()
    actor_id = actor_id_ctx.get()
    if request_id:
        event_dict["request_id"] = request_id
    if organization_id:
        event_dict["organization_id"] = organization_id
    if actor_id:
        event_dict["actor_id"] = actor_id
    return event_dict


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_context,
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
