"""Identity-specific domain errors — all subclass the shared_kernel
hierarchy (Domain Model §1's rule: contexts express errors in terms of the
shared vocabulary, not invent parallel exception trees).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import (
    AuthenticationFailedError,
    ConcurrencyConflictError,
    GuardRejectedError,
    IllegalStateTransitionError,
    NotFoundError,
    ValidationFailedError,
)


class TenantNotFoundError(NotFoundError):
    pass


class TenantSlugAlreadyExistsError(GuardRejectedError):
    pass


class UserNotFoundError(NotFoundError):
    pass


class EmailAlreadyRegisteredError(GuardRejectedError):
    pass


class InvalidCredentialsError(AuthenticationFailedError):
    """Deliberately identical whether the email doesn't exist or the
    password is wrong — never leak which one it was (a standard
    authentication hardening measure, and the same "don't leak existence"
    principle API Resource Model §9 applies to tenant-scoped 404s). Maps to
    401, not 403: the caller has not established any valid identity yet —
    see shared_kernel.errors.AuthenticationFailedError's docstring.
    """


class UserNotActiveError(AuthenticationFailedError):
    """Login (or token-refresh) attempted against a user whose status
    isn't ACTIVE (invited, suspended, or deactivated) — 401, not 403, for
    the same reason as InvalidCredentialsError: there is no valid session
    to be authorized against in the first place.
    """


class IllegalUserStatusTransitionError(IllegalStateTransitionError):
    pass


class LastOwnerRemovalError(GuardRejectedError):
    """A tenant must always retain at least one OWNER — refuses a role
    change or status change that would leave zero.
    """


class WeakPasswordError(ValidationFailedError):
    pass


class InvalidOrExpiredTokenError(AuthenticationFailedError):
    """Covers refresh tokens, password-reset tokens, and invitation tokens
    uniformly — all three are opaque, hashed, expiring, single-use-or-
    revocable bearer credentials with the same failure shape, and the same
    401 classification: presenting one that's invalid/expired/consumed
    means the caller isn't authenticated for the action they're claiming,
    not that a business-data invariant was violated (hence
    AuthenticationFailedError, not GuardRejectedError, despite the name
    sounding guard-like).
    """


class RefreshTokenReuseDetectedError(AuthenticationFailedError):
    """A revoked/rotated refresh token was presented again — a strong
    signal of token theft. Distinct from InvalidOrExpiredTokenError because
    the handler's response differs: this triggers revoking every active
    refresh token for the user, not just rejecting the one request. Still
    fundamentally an authentication failure (401), same reasoning as
    InvalidOrExpiredTokenError.
    """


class RoleNotFoundError(NotFoundError):
    pass


class OptimisticConcurrencyError(ConcurrencyConflictError):
    pass
