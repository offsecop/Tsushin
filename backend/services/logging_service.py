"""
Structured logging utilities for Tsushin.

Provides:
- JsonFormatter: emits each log record as a single JSON line.
- request_id context variable: populated by RequestIdMiddleware.
"""

import json
import logging
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Per-request context
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "tsn-core",
        }

        rid = request_id_ctx.get("")
        if rid:
            payload["request_id"] = rid

        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return json.dumps(payload, default=str)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Generates a UUID for every inbound HTTP request, stores it in a
    contextvar so log records can include it, and returns it as a
    response header (X-Request-Id).
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            request_id_ctx.reset(token)
