"""Notification-specific domain errors — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import NotFoundError, ValidationFailedError


class AlertRuleNotFoundError(NotFoundError):
    pass


class NotificationSubscriptionNotFoundError(NotFoundError):
    pass


class NotificationNotFoundError(NotFoundError):
    pass


class InvalidAlertRuleError(ValidationFailedError):
    """``stage_type`` must be set when ``subject_type`` is ``STAGE_RESULT``
    (and only then) — the reader needs to know which stage to query."""


class InvalidNotificationSubscriptionError(ValidationFailedError):
    """A channel was selected without the recipient detail it needs
    (``email_address`` for ``EMAIL``, ``phone_number`` for ``SMS``)."""
