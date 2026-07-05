"""Establishes ``traceId`` for every request before anything downstream —
including error handling — runs. Must be the outermost middleware in the
chain (Implementation Bootstrap §12): every log line and every error
response from this point forward is expected to carry a ``traceId``.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from georisk.observability.logging import trace_id_var


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        token = trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            trace_id_var.reset(token)
        response.headers["X-Trace-Id"] = trace_id
        return response
