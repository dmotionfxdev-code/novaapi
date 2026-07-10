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
    # Sprint D: application-layer rate limiting (api/middleware/
    # rate_limiting.py) — the one entry this module's original docstring
    # comment predicted "growing by one" for.
    domain_errors.RateLimitExceededError: 429,
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
    response = JSONResponse(status_code=status, content=body)
    retry_after = getattr(exc, "retry_after_seconds", None)
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


# Sprint D exception hardening: every mapped domain error above (400-429)
# already carries a message the domain/application layer deliberately
# crafted to be safe to show a client (e.g. "Invalid email or password") —
# those pass through _problem_response's str(exc) unchanged, as before.
# An exception that reaches the line below, by contrast, is one NO layer
# of this codebase recognized or intended to surface — its message may be
# a raw SQL error, a file path, a third-party library's internal repr, or
# anything else never vetted for a client to see. Sprint D closes the one
# confirmed leak this project's own SECURITY_REVIEW.md documented: this
# generic message (plus the type name below) replaces whatever str(exc)
# would otherwise have been; the real exception is still logged in full
# server-side (with its traceId) for a support engineer to look up.
_SAFE_UNHANDLED_MESSAGE = (
    "An unexpected error occurred. Please contact support with this trace ID."
)


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type, status in _STATUS_MAP.items():

        def _make_handler(bound_status: int) -> ExceptionHandler:
            async def _handler(request: Request, exc: Exception) -> JSONResponse:
                return _problem_response(request, exc, bound_status)

            return _handler

        app.add_exception_handler(exc_type, _make_handler(status))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak an internal stack trace — or even the internal
        # exception's own message/class name — to the client: log it in
        # full server-side, return only a generic message, the correct
        # 500 status, and a traceId a support engineer can look up against
        # that log line.
        trace_id = _trace_id(request)
        logger.exception(
            "Unhandled exception", extra={"path": str(request.url.path), "traceId": trace_id}
        )
        body = {
            "type": "https://docs.firas.dev/errors/InternalServerError",
            "title": "InternalServerError",
            "status": 500,
            "detail": _SAFE_UNHANDLED_MESSAGE,
            "instance": str(request.url.path),
            "traceId": trace_id,
            "errors": [],
        }
        return JSONResponse(status_code=500, content=body)
