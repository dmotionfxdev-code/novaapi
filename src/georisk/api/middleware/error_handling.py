"""Translates the domain exception hierarchy (``shared_kernel.errors``) into
RFC 7807 Problem Details responses (API Resource Model §9). This is the only
place in the codebase that maps a domain error to an HTTP status code — no
domain or application code should ever construct an HTTP response directly.

Registered last in the middleware/handler chain so it can catch exceptions
raised anywhere upstream of it (Implementation Bootstrap §3).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from georisk.observability.logging import trace_id_var
from georisk.shared_kernel import errors as domain_errors

ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]

logger = logging.getLogger("georisk.unhandled")

# Every status code here matches API Resource Model §9's table exactly.
# 429 (rate limit) and 503 (upstream dependency unavailable) aren't wired
# yet because nothing rate-limits or calls an external adapter until later
# sprints — this map is sized to grow by one entry each when they do, not to
# be restructured (Implementation Bootstrap, closing rationale of §13).
_STATUS_MAP: dict[type[Exception], int] = {
    domain_errors.ValidationFailedError: 400,
    # AuthenticationFailedError (401) must be registered as a handler
    # BEFORE AuthorizationDeniedError (403) even though dict iteration
    # order doesn't matter for lookup correctness here — Starlette's
    # exception-handler lookup walks each exception's MRO independently,
    # not this dict's insertion order, so this ordering is documentation,
    # not a functional requirement. What *is* required: the two stay
    # distinct types, neither a subclass of the other, so a given error
    # resolves to exactly one status (Identity context, Roadmap Sprint 1 —
    # see AuthenticationFailedError's docstring for why this split exists).
    domain_errors.AuthenticationFailedError: 401,
    domain_errors.AuthorizationDeniedError: 403,
    domain_errors.NotFoundError: 404,
    domain_errors.GuardRejectedError: 422,
    domain_errors.IllegalStateTransitionError: 409,
    domain_errors.ConcurrencyConflictError: 409,
    domain_errors.IdempotencyConflictError: 409,
}


def _trace_id(request: Request) -> str:
    # Read the trace id TraceContextMiddleware already established for this
    # request (it must run outer to the exception-handling layer for this to
    # be populated — see api/app.py's middleware registration order). Fall
    # back to the raw request header, and only then a fresh id, so this
    # function is still safe to call in a context where that middleware
    # somehow didn't run (e.g. a unit test hitting a handler directly).
    return trace_id_var.get() or request.headers.get("X-Trace-Id") or str(uuid.uuid4())


def _problem_response(request: Request, exc: Exception, status: int) -> JSONResponse:
    body = {
        "type": f"https://docs.firas.dev/errors/{type(exc).__name__}",
        "title": type(exc).__name__,
        "status": status,
        "detail": str(exc),
        "instance": str(request.url.path),
        "traceId": _trace_id(request),
        "errors": getattr(exc, "field_errors", []),
    }
    return JSONResponse(status_code=status, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type, status in _STATUS_MAP.items():

        def _make_handler(bound_status: int) -> ExceptionHandler:
            async def _handler(request: Request, exc: Exception) -> JSONResponse:
                return _problem_response(request, exc, bound_status)

            return _handler

        app.add_exception_handler(exc_type, _make_handler(status))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak an internal stack trace to the client — log it fully,
        # return an opaque 500 with only the traceId a support engineer can
        # look up in the logs.
        logger.exception("Unhandled exception", extra={"path": str(request.url.path)})
        return _problem_response(request, exc, 500)
