"""Repository-level integration tests against a real Postgres instance —
confirms all three aggregates' domain<->ORM mapping round-trips
correctly, that ``AlertRule``/``NotificationSubscription`` save() inserts
on first save and updates in place thereafter (long-lived configuration,
not versioned evidence), and that ``Notification`` history pagination
works.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertOperator,
    AlertSeverity,
    AlertSubjectType,
    NotificationChannelType,
)
from georisk.contexts.notification.infrastructure.repositories import (
    SqlAlchemyAlertRuleRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyNotificationSubscriptionRepository,
)

pytestmark = pytest.mark.integration


async def test_alert_rule_round_trips_and_updates_in_place(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    rule, _event = AlertRule.create(
        tenant_id=tenant_id,
        name="High Flood Risk",
        subject_type=AlertSubjectType.STAGE_RESULT,
        hazard_type="FLOOD",
        stage_type="RISK",
        metric_code="flood_risk_index",
        operator=AlertOperator.GREATER_THAN,
        threshold=0.5,
        severity=AlertSeverity.HIGH,
        created_by="analyst-1",
    )
    repo = SqlAlchemyAlertRuleRepository(db_session)
    await repo.save(rule)
    await db_session.flush()

    fetched = await repo.get_by_id(rule.id)
    assert fetched is not None
    assert fetched.metric_code == "flood_risk_index"
    assert fetched.threshold == 0.5
    assert fetched.is_active is True

    rule.update_threshold(threshold=0.65, changed_by="analyst-2")
    rule.deactivate(changed_by="analyst-2")
    await repo.save(rule)
    await db_session.flush()

    refetched = await repo.get_by_id(rule.id)
    assert refetched is not None
    assert refetched.threshold == 0.65
    assert refetched.is_active is False

    active = await repo.list_active_by_tenant(tenant_id)
    assert active == []
    all_rules = await repo.list_by_tenant(tenant_id)
    assert len(all_rules) == 1


async def test_notification_subscription_round_trips_and_updates_in_place(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    subscription, _event = NotificationSubscription.subscribe(
        tenant_id=tenant_id,
        user_id=UserId.new(),
        hazard_type="FLOOD",
        channels=frozenset({NotificationChannelType.EMAIL, NotificationChannelType.IN_APP}),
        email_address="ops@example.com",
        phone_number=None,
    )
    repo = SqlAlchemyNotificationSubscriptionRepository(db_session)
    await repo.save(subscription)
    await db_session.flush()

    fetched = await repo.get_by_id(subscription.id)
    assert fetched is not None
    assert fetched.email_address == "ops@example.com"
    assert fetched.channels == frozenset(
        {NotificationChannelType.EMAIL, NotificationChannelType.IN_APP}
    )
    assert fetched.is_active is True

    subscription.deactivate(changed_by="analyst-1")
    await repo.save(subscription)
    await db_session.flush()

    refetched = await repo.get_by_id(subscription.id)
    assert refetched is not None
    assert refetched.is_active is False

    active = await repo.list_active_by_tenant(tenant_id)
    assert active == []


async def test_notification_round_trips_and_history_is_paginated(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    rule, _e1 = AlertRule.create(
        tenant_id=tenant_id,
        name="Rule",
        subject_type=AlertSubjectType.PREDICTION,
        hazard_type=None,
        stage_type=None,
        metric_code="rmse",
        operator=AlertOperator.GREATER_THAN,
        threshold=5.0,
        severity=AlertSeverity.MEDIUM,
        created_by="analyst-1",
    )
    subscription, _e2 = NotificationSubscription.subscribe(
        tenant_id=tenant_id,
        user_id=UserId.new(),
        hazard_type=None,
        channels=frozenset({NotificationChannelType.IN_APP}),
        email_address=None,
        phone_number=None,
    )
    notification_repo = SqlAlchemyNotificationRepository(db_session)

    for i in range(3):
        notification, _event = Notification.sent(
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            alert_rule_id=rule.id,
            subscription_id=subscription.id,
            channel=NotificationChannelType.IN_APP,
            recipient=str(subscription.user_id),
            severity=rule.severity,
            metric_code=rule.metric_code,
            triggered_value=6.0 + i,
            threshold=rule.threshold,
            operator=rule.operator,
            message=f"rmse {6.0 + i} > 5.0",
        )
        await notification_repo.save(notification)
    await db_session.flush()

    by_assessment = await notification_repo.list_by_assessment(tenant_id, assessment_id)
    assert len(by_assessment) == 3

    page1, cursor1, has_more1 = await notification_repo.list_by_tenant(
        tenant_id, limit=2, cursor=None
    )
    assert len(page1) == 2
    assert has_more1 is True

    page2, _cursor2, has_more2 = await notification_repo.list_by_tenant(
        tenant_id, limit=2, cursor=cursor1
    )
    assert len(page2) == 1
    assert has_more2 is False
