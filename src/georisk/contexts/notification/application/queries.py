"""Query handlers — read-only, never mutate, never go through the command
pipeline (Application Layer §3/§4). Same pattern as every prior context.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.contexts.notification.domain.errors import (
    AlertRuleNotFoundError,
    NotificationNotFoundError,
    NotificationSubscriptionNotFoundError,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertRuleId,
    NotificationId,
    NotificationSubscriptionId,
)
from georisk.contexts.notification.infrastructure.repositories import (
    SqlAlchemyAlertRuleRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyNotificationSubscriptionRepository,
)
from georisk.shared_kernel.types import CursorPage


class GetAlertRuleQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, alert_rule_id: AlertRuleId) -> AlertRule:
        rule = await SqlAlchemyAlertRuleRepository(self._session).get_by_id(alert_rule_id)
        if rule is None or rule.tenant_id != tenant_id:
            raise AlertRuleNotFoundError(f"AlertRule {alert_rule_id} not found")
        return rule


class ListAlertRulesQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId) -> list[AlertRule]:
        return await SqlAlchemyAlertRuleRepository(self._session).list_by_tenant(tenant_id)


class GetNotificationSubscriptionQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, subscription_id: NotificationSubscriptionId
    ) -> NotificationSubscription:
        subscription = await SqlAlchemyNotificationSubscriptionRepository(
            self._session
        ).get_by_id(subscription_id)
        if subscription is None or subscription.tenant_id != tenant_id:
            raise NotificationSubscriptionNotFoundError(
                f"NotificationSubscription {subscription_id} not found"
            )
        return subscription


class ListNotificationSubscriptionsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId) -> list[NotificationSubscription]:
        return await SqlAlchemyNotificationSubscriptionRepository(self._session).list_by_tenant(
            tenant_id
        )


class GetNotificationQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, notification_id: NotificationId) -> Notification:
        notification = await SqlAlchemyNotificationRepository(self._session).get_by_id(
            notification_id
        )
        if notification is None or notification.tenant_id != tenant_id:
            raise NotificationNotFoundError(f"Notification {notification_id} not found")
        return notification


class ListNotificationsByAssessmentQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> list[Notification]:
        return await SqlAlchemyNotificationRepository(self._session).list_by_assessment(
            tenant_id, assessment_id
        )


@dataclass(frozen=True, slots=True)
class ListNotificationsByTenantParams:
    tenant_id: TenantId
    limit: int = 25
    cursor: str | None = None


class ListNotificationsByTenantQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, params: ListNotificationsByTenantParams) -> CursorPage[Notification]:
        limit = min(max(params.limit, 1), 100)
        notifications, next_cursor, has_more = await SqlAlchemyNotificationRepository(
            self._session
        ).list_by_tenant(params.tenant_id, limit=limit, cursor=params.cursor)
        return CursorPage(items=notifications, next_cursor=next_cursor, has_more=has_more)
