"""Concrete SQLAlchemy repositories implementing
``contexts/notification/domain/repositories.py``'s Protocols.
"""

from __future__ import annotations

import base64
import json
import uuid as uuid_module
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from georisk.contexts.notification.infrastructure import mappers
from georisk.contexts.notification.infrastructure.models import (
    AlertRuleModel,
    NotificationModel,
    NotificationSubscriptionModel,
)


class SqlAlchemyAlertRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, alert_rule_id: AlertRuleId) -> AlertRule | None:
        model = await self._session.get(AlertRuleModel, alert_rule_id.value)
        return mappers.alert_rule_to_domain(model) if model else None

    async def list_by_tenant(self, tenant_id: TenantId) -> list[AlertRule]:
        query = (
            select(AlertRuleModel)
            .where(AlertRuleModel.tenant_id == tenant_id.value)
            .order_by(AlertRuleModel.created_at)
        )
        result = await self._session.execute(query)
        return [mappers.alert_rule_to_domain(m) for m in result.scalars().all()]

    async def list_active_by_tenant(self, tenant_id: TenantId) -> list[AlertRule]:
        query = select(AlertRuleModel).where(
            AlertRuleModel.tenant_id == tenant_id.value, AlertRuleModel.is_active.is_(True)
        )
        result = await self._session.execute(query)
        return [mappers.alert_rule_to_domain(m) for m in result.scalars().all()]

    async def save(self, rule: AlertRule) -> None:
        model = await self._session.get(AlertRuleModel, rule.id.value)
        if model is None:
            model = AlertRuleModel()
            mappers.apply_alert_rule_to_model(rule, model)
            self._session.add(model)
            return
        mappers.apply_alert_rule_to_model(rule, model)


class SqlAlchemyNotificationSubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, subscription_id: NotificationSubscriptionId
    ) -> NotificationSubscription | None:
        model = await self._session.get(NotificationSubscriptionModel, subscription_id.value)
        return mappers.notification_subscription_to_domain(model) if model else None

    async def list_by_tenant(self, tenant_id: TenantId) -> list[NotificationSubscription]:
        query = select(NotificationSubscriptionModel).where(
            NotificationSubscriptionModel.tenant_id == tenant_id.value
        )
        result = await self._session.execute(query)
        return [mappers.notification_subscription_to_domain(m) for m in result.scalars().all()]

    async def list_active_by_tenant(self, tenant_id: TenantId) -> list[NotificationSubscription]:
        query = select(NotificationSubscriptionModel).where(
            NotificationSubscriptionModel.tenant_id == tenant_id.value,
            NotificationSubscriptionModel.is_active.is_(True),
        )
        result = await self._session.execute(query)
        return [mappers.notification_subscription_to_domain(m) for m in result.scalars().all()]

    async def save(self, subscription: NotificationSubscription) -> None:
        model = await self._session.get(NotificationSubscriptionModel, subscription.id.value)
        if model is None:
            model = NotificationSubscriptionModel()
            mappers.apply_notification_subscription_to_model(subscription, model)
            self._session.add(model)
            return
        mappers.apply_notification_subscription_to_model(subscription, model)


class SqlAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, notification_id: NotificationId) -> Notification | None:
        model = await self._session.get(NotificationModel, notification_id.value)
        return mappers.notification_to_domain(model) if model else None

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[Notification]:
        query = (
            select(NotificationModel)
            .where(
                NotificationModel.tenant_id == tenant_id.value,
                NotificationModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(NotificationModel.created_at.desc())
        )
        result = await self._session.execute(query)
        return [mappers.notification_to_domain(m) for m in result.scalars().all()]

    async def list_by_tenant(
        self, tenant_id: TenantId, *, limit: int, cursor: str | None
    ) -> tuple[list[Notification], str | None, bool]:
        query = select(NotificationModel).where(NotificationModel.tenant_id == tenant_id.value)
        query = query.order_by(NotificationModel.created_at, NotificationModel.id)

        if cursor:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            cursor_created_at = datetime.fromisoformat(decoded["created_at"])
            cursor_id = uuid_module.UUID(decoded["id"])
            query = query.where(
                (NotificationModel.created_at > cursor_created_at)
                | (
                    (NotificationModel.created_at == cursor_created_at)
                    & (NotificationModel.id > cursor_id)
                )
            )
        query = query.limit(limit + 1)

        result = await self._session.execute(query)
        models = list(result.scalars().all())
        has_more = len(models) > limit
        models = models[:limit]
        notifications = [mappers.notification_to_domain(m) for m in models]

        next_cursor = None
        if has_more and models:
            last = models[-1]
            payload = json.dumps({"created_at": last.created_at.isoformat(), "id": str(last.id)})
            next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()

        return notifications, next_cursor, has_more

    async def save(self, notification: Notification) -> None:
        model = NotificationModel()
        mappers.apply_notification_to_model(notification, model)
        self._session.add(model)
