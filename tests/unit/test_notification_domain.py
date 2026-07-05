"""Domain-layer unit tests for Notification's three aggregates
(``AlertRule``, ``NotificationSubscription``, ``Notification``) and the
``AlertOperator.evaluate`` pure function — pure logic, no I/O.
"""

from __future__ import annotations

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.contexts.notification.domain.errors import (
    InvalidAlertRuleError,
    InvalidNotificationSubscriptionError,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertOperator,
    AlertSeverity,
    AlertSubjectType,
    NotificationChannelType,
    NotificationStatus,
)

pytestmark = pytest.mark.unit


# --- AlertOperator -----------------------------------------------------


def test_alert_operator_evaluate() -> None:
    assert AlertOperator.GREATER_THAN.evaluate(0.6, 0.5) is True
    assert AlertOperator.GREATER_THAN.evaluate(0.4, 0.5) is False
    assert AlertOperator.LESS_THAN.evaluate(0.4, 0.5) is True
    assert AlertOperator.GREATER_THAN_OR_EQUAL.evaluate(0.5, 0.5) is True
    assert AlertOperator.LESS_THAN_OR_EQUAL.evaluate(0.5, 0.5) is True


# --- AlertRule -----------------------------------------------------------


def test_create_stage_result_alert_rule() -> None:
    rule, event = AlertRule.create(
        tenant_id=TenantId.new(),
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
    assert rule.is_active is True
    assert rule.hazard_type == "FLOOD"
    assert event.event_type == "notification.AlertRuleCreated"
    assert event.threshold == 0.5


def test_create_stage_result_rule_requires_stage_type() -> None:
    with pytest.raises(InvalidAlertRuleError, match="stage_type is required"):
        AlertRule.create(
            tenant_id=TenantId.new(),
            name="Bad rule",
            subject_type=AlertSubjectType.STAGE_RESULT,
            hazard_type="FLOOD",
            stage_type=None,
            metric_code="flood_risk_index",
            operator=AlertOperator.GREATER_THAN,
            threshold=0.5,
            severity=AlertSeverity.HIGH,
            created_by="analyst-1",
        )


def test_create_prediction_rule_rejects_stage_type() -> None:
    with pytest.raises(InvalidAlertRuleError, match="only meaningful"):
        AlertRule.create(
            tenant_id=TenantId.new(),
            name="Bad rule",
            subject_type=AlertSubjectType.PREDICTION,
            hazard_type=None,
            stage_type="RISK",
            metric_code="rmse",
            operator=AlertOperator.GREATER_THAN,
            threshold=1.0,
            severity=AlertSeverity.MEDIUM,
            created_by="analyst-1",
        )


def test_create_prediction_rmse_rule() -> None:
    rule, _event = AlertRule.create(
        tenant_id=TenantId.new(),
        name="High RMSE",
        subject_type=AlertSubjectType.PREDICTION,
        hazard_type=None,
        stage_type=None,
        metric_code="rmse",
        operator=AlertOperator.GREATER_THAN,
        threshold=5.0,
        severity=AlertSeverity.MEDIUM,
        created_by="analyst-1",
    )
    assert rule.subject_type is AlertSubjectType.PREDICTION
    assert rule.stage_type is None


def test_create_validation_r_squared_rule() -> None:
    rule, _event = AlertRule.create(
        tenant_id=TenantId.new(),
        name="Low R-squared",
        subject_type=AlertSubjectType.VALIDATION,
        hazard_type=None,
        stage_type=None,
        metric_code="r_squared",
        operator=AlertOperator.LESS_THAN,
        threshold=0.5,
        severity=AlertSeverity.CRITICAL,
        created_by="analyst-1",
    )
    assert rule.operator is AlertOperator.LESS_THAN


def test_update_threshold_activate_deactivate() -> None:
    rule, _event = AlertRule.create(
        tenant_id=TenantId.new(),
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
    updated_event = rule.update_threshold(threshold=7.5, changed_by="analyst-2")
    assert rule.threshold == 7.5
    assert updated_event.event_type == "notification.AlertRuleUpdated"

    deactivated_event = rule.deactivate(changed_by="analyst-2")
    assert rule.is_active is False
    assert deactivated_event.event_type == "notification.AlertRuleDeactivated"

    activated_event = rule.activate(changed_by="analyst-2")
    assert rule.is_active is True
    assert activated_event.event_type == "notification.AlertRuleActivated"


# --- NotificationSubscription --------------------------------------------


def test_subscribe_with_in_app_only() -> None:
    subscription, event = NotificationSubscription.subscribe(
        tenant_id=TenantId.new(),
        user_id=UserId.new(),
        hazard_type=None,
        channels=frozenset({NotificationChannelType.IN_APP}),
        email_address=None,
        phone_number=None,
    )
    assert subscription.is_active is True
    assert event.event_type == "notification.NotificationSubscriptionCreated"
    assert event.channels == ["IN_APP"]


def test_subscribe_email_requires_email_address() -> None:
    with pytest.raises(InvalidNotificationSubscriptionError, match="email_address is required"):
        NotificationSubscription.subscribe(
            tenant_id=TenantId.new(),
            user_id=UserId.new(),
            hazard_type=None,
            channels=frozenset({NotificationChannelType.EMAIL}),
            email_address=None,
            phone_number=None,
        )


def test_subscribe_sms_requires_phone_number() -> None:
    with pytest.raises(InvalidNotificationSubscriptionError, match="phone_number is required"):
        NotificationSubscription.subscribe(
            tenant_id=TenantId.new(),
            user_id=UserId.new(),
            hazard_type=None,
            channels=frozenset({NotificationChannelType.SMS}),
            email_address=None,
            phone_number=None,
        )


def test_subscribe_requires_at_least_one_channel() -> None:
    with pytest.raises(InvalidNotificationSubscriptionError, match="at least one channel"):
        NotificationSubscription.subscribe(
            tenant_id=TenantId.new(),
            user_id=UserId.new(),
            hazard_type=None,
            channels=frozenset(),
            email_address=None,
            phone_number=None,
        )


def test_subscription_activate_deactivate() -> None:
    subscription, _event = NotificationSubscription.subscribe(
        tenant_id=TenantId.new(),
        user_id=UserId.new(),
        hazard_type=None,
        channels=frozenset({NotificationChannelType.IN_APP}),
        email_address=None,
        phone_number=None,
    )
    deactivated_event = subscription.deactivate(changed_by="analyst-1")
    assert subscription.is_active is False
    assert deactivated_event.event_type == "notification.NotificationSubscriptionDeactivated"
    activated_event = subscription.activate(changed_by="analyst-1")
    assert subscription.is_active is True
    assert activated_event.event_type == "notification.NotificationSubscriptionActivated"


# --- Notification ---------------------------------------------------------


def test_notification_sent() -> None:
    rule, _e1 = AlertRule.create(
        tenant_id=TenantId.new(),
        name="Rule",
        subject_type=AlertSubjectType.STAGE_RESULT,
        hazard_type="FLOOD",
        stage_type="RISK",
        metric_code="flood_risk_index",
        operator=AlertOperator.GREATER_THAN,
        threshold=0.5,
        severity=AlertSeverity.HIGH,
        created_by="analyst-1",
    )
    subscription, _e2 = NotificationSubscription.subscribe(
        tenant_id=rule.tenant_id,
        user_id=UserId.new(),
        hazard_type=None,
        channels=frozenset({NotificationChannelType.IN_APP}),
        email_address=None,
        phone_number=None,
    )
    notification, event = Notification.sent(
        tenant_id=rule.tenant_id,
        assessment_id="11111111-1111-1111-1111-111111111111",
        alert_rule_id=rule.id,
        subscription_id=subscription.id,
        channel=NotificationChannelType.IN_APP,
        recipient=str(subscription.user_id),
        severity=rule.severity,
        metric_code=rule.metric_code,
        triggered_value=0.65,
        threshold=rule.threshold,
        operator=rule.operator,
        message="flood_risk_index 0.65 > 0.5",
    )
    assert notification.status == NotificationStatus.SENT
    assert notification.error is None
    assert event.event_type == "notification.NotificationSent"
    assert event.severity == "HIGH"


def test_notification_failed() -> None:
    rule, _e1 = AlertRule.create(
        tenant_id=TenantId.new(),
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
        tenant_id=rule.tenant_id,
        user_id=UserId.new(),
        hazard_type=None,
        channels=frozenset({NotificationChannelType.EMAIL}),
        email_address="ops@example.com",
        phone_number=None,
    )
    notification, event = Notification.failed(
        tenant_id=rule.tenant_id,
        assessment_id="11111111-1111-1111-1111-111111111111",
        alert_rule_id=rule.id,
        subscription_id=subscription.id,
        channel=NotificationChannelType.EMAIL,
        recipient="ops@example.com",
        severity=rule.severity,
        metric_code=rule.metric_code,
        triggered_value=7.2,
        threshold=rule.threshold,
        operator=rule.operator,
        message="rmse 7.2 > 5.0",
        error="SMTP not configured",
    )
    assert notification.status == NotificationStatus.FAILED
    assert notification.error == "SMTP not configured"
    assert event.event_type == "notification.NotificationDeliveryFailed"
