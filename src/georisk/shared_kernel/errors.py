"""Domain-level exception hierarchy.

Pure Python, zero HTTP awareness — every bounded context's domain and
application layers raise these; the interface layer (``api/middleware/
error_handling.py``) is the only place that knows how to turn one into an
HTTP response (Application Layer §2; API Resource Model §9).

No hazard-specific or context-specific subclasses live here — those belong
to each context's own domain layer once it exists. This module only defines
the shared vocabulary every context's errors are expressed in terms of.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for every error raised by domain or application code."""


class NotFoundError(DomainError):
    """The requested aggregate/entity does not exist, or isn't visible to
    the current tenant — deliberately the same outward response for both
    cases (API Resource Model §9: existence is never leaked across tenants).
    """


class ValidationFailedError(DomainError):
    """Malformed input caught before any aggregate was touched."""

    def __init__(self, message: str, field_errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.field_errors = field_errors or []


class GuardRejectedError(DomainError):
    """An aggregate invariant or command guard refused the request — the
    command was well-formed but the aggregate's current state/data doesn't
    satisfy its precondition (e.g. ``StartAnalysis`` before data sufficiency
    is met, Application Layer §1).
    """


class IllegalStateTransitionError(DomainError):
    """A command was legal in form but not from the aggregate's current
    lifecycle state (Domain Model §6's transition table).
    """


class ConcurrencyConflictError(DomainError):
    """Optimistic-concurrency version check failed — two commands raced
    against the same aggregate instance (Application Layer §9).
    """


class AuthenticationFailedError(DomainError):
    """No valid identity established at all — missing/invalid/expired
    credentials or token, or the account isn't in a state that can
    authenticate (API Resource Model §9's "Not authenticated" -> 401
    category). Distinct from :class:`AuthorizationDeniedError`, which
    requires a *successfully* authenticated caller who simply isn't
    permitted to do the specific thing they asked for (-> 403). Sprint 1
    is the first bounded context to actually distinguish these two — an
    earlier draft of this module conflated them under one 403 for
    everything, which put login failures and invalid tokens at the wrong
    HTTP status code.
    """


class AuthorizationDeniedError(DomainError):
    """Authenticated, but not permitted to perform this action."""


class IdempotencyConflictError(DomainError):
    """An idempotency key was reused with a materially different payload
    than its first use (Application Layer §11) — distinct from a true
    replay, which returns the original response rather than raising.
    """


class RateLimitExceededError(DomainError):
    """Sprint D — the caller has exceeded an application-layer rate limit
    on a specific action (login, registration, password reset, token
    refresh, analysis/prediction execution, or upload). Maps to 429, not
    400/403: the request is well-formed and the caller may be fully
    authorized — they've simply made too many of them, too fast.
    """

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
