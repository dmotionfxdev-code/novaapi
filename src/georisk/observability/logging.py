"""Structured JSON logging with trace/tenant correlation.

Every log line carries ``traceId``/``tenantId`` via context variables
(Infrastructure Architecture §23) so a single logical operation — spanning
an API request, its Celery jobs, and every command they issue — can be
correlated across processes without a distributed tracing backend being
strictly required to answer "what happened for this request."

``assessmentId`` is deliberately not a context variable set by middleware —
it's attached to individual log calls once a command/query handler has one
available (Roadmap Sprint 2 onward), since it isn't known before request
routing/deserialization the way ``traceId`` is.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from georisk.settings import Settings

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
tenant_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tenant_id", default=None
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "traceId": trace_id_var.get(),
            "tenantId": tenant_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
