"""Repository interfaces — domain layer contracts (Application Layer §1:
one repository per aggregate root). Concrete SQLAlchemy implementations
live in ``contexts/notification/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertRuleId,
    NotificationId,
    NotificationSubscriptionId,
)


class AlertRuleRepository(Protocol):
    async def get_by_id(self, alert_rule_id: AlertRuleId) -> AlertRule | None: ...

    async def list_by_tenant(self, tenant_id: TenantId) -> list[AlertRule]: ...

    async def list_active_by_tenant(self, tenant_id: TenantId) -> list[AlertRule]:
        """What the Early Warning Engine evaluates — every currently-active
        rule for this tenant, regardless of which assessment triggered the
        evaluation (hazard-type filtering happens in the engine, not here).
        """
        ...

    async def save(self, rule: AlertRule) -> None:
        """Insert on first save; update-in-place thereafter (same
        "long-lived configuration, not versioned evidence" reasoning as
        ``Report``'s DRAFT->FINALIZED save — see that repository's
        docstring)."""
        ...


class NotificationSubscriptionRepository(Protocol):
    async def get_by_id(
        self, subscription_id: NotificationSubscriptionId
    ) -> NotificationSubscription | None: ...

    async def list_by_tenant(self, tenant_id: TenantId) -> list[NotificationSubscription]: ...

    async def list_active_by_tenant(
        self, tenant_id: TenantId
    ) -> list[NotificationSubscription]: ...

    async def save(self, subscription: NotificationSubscription) -> None: ...


class NotificationRepository(Protocol):
    async def get_by_id(self, notification_id: NotificationId) -> Notification | None: ...

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[Notification]: ...

    async def list_by_tenant(
        self, tenant_id: TenantId, *, limit: int, cursor: str | None
    ) -> tuple[list[Notification], str | None, bool]:
        """"Notification History" (Sprint 11 requirement #4) — cursor
        pagination keyed on ``(created_at, id)``, the same convention every
        prior context's history-style list query already uses."""
        ...

    async def save(self, notification: Notification) -> None:
        """Always inserts — a ``Notification`` is write-once evidence, the
        same "immutable once created" pattern as ``StageResult``/
        ``PredictionRun``."""
        ...
