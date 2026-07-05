"""Maps between Notification's domain entities and their SQLAlchemy ORM
representations. Free functions, not methods on either side (same pattern
as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module

from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertOperator,
    AlertRuleId,
    AlertSeverity,
    AlertSubjectType,
    NotificationChannelType,
    NotificationId,
    NotificationStatus,
    NotificationSubscriptionId,
)
from georisk.contexts.notification.infrastructure.models import (
    AlertRuleModel,
    NotificationModel,
    NotificationSubscriptionModel,
)


def alert_rule_to_domain(model: AlertRuleModel) -> AlertRule:
    return AlertRule(
        id=AlertRuleId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        name=model.name,
        subject_type=AlertSubjectType(model.subject_type),
        hazard_type=model.hazard_type,
        stage_type=model.stage_type,
        metric_code=model.metric_code,
        operator=AlertOperator(model.operator),
        threshold=model.threshold,
        severity=AlertSeverity(model.severity),
        is_active=model.is_active,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def apply_alert_rule_to_model(entity: AlertRule, model: AlertRuleModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.name = entity.name
    model.subject_type = entity.subject_type.value
    model.hazard_type = entity.hazard_type
    model.stage_type = entity.stage_type
    model.metric_code = entity.metric_code
    model.operator = entity.operator.value
    model.threshold = entity.threshold
    model.severity = entity.severity.value
    model.is_active = entity.is_active
    model.created_by = entity.created_by
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at


def notification_subscription_to_domain(
    model: NotificationSubscriptionModel,
) -> NotificationSubscription:
    return NotificationSubscription(
        id=NotificationSubscriptionId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        user_id=UserId(value=model.user_id),
        hazard_type=model.hazard_type,
        channels=frozenset(NotificationChannelType(c) for c in model.channels),
        email_address=model.email_address,
        phone_number=model.phone_number,
        is_active=model.is_active,
        created_at=model.created_at,
    )


def apply_notification_subscription_to_model(
    entity: NotificationSubscription, model: NotificationSubscriptionModel
) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.user_id = entity.user_id.value
    model.hazard_type = entity.hazard_type
    model.channels = sorted(c.value for c in entity.channels)
    model.email_address = entity.email_address
    model.phone_number = entity.phone_number
    model.is_active = entity.is_active
    model.created_at = entity.created_at


def notification_to_domain(model: NotificationModel) -> Notification:
    return Notification(
        id=NotificationId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        alert_rule_id=AlertRuleId(value=model.alert_rule_id),
        subscription_id=NotificationSubscriptionId(value=model.subscription_id),
        channel=NotificationChannelType(model.channel),
        recipient=model.recipient,
        severity=AlertSeverity(model.severity),
        metric_code=model.metric_code,
        triggered_value=model.triggered_value,
        threshold=model.threshold,
        operator=AlertOperator(model.operator),
        message=model.message,
        status=NotificationStatus(model.status),
        error=model.error,
        created_at=model.created_at,
    )


def apply_notification_to_model(entity: Notification, model: NotificationModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.alert_rule_id = entity.alert_rule_id.value
    model.subscription_id = entity.subscription_id.value
    model.channel = entity.channel.value
    model.recipient = entity.recipient
    model.severity = entity.severity.value
    model.metric_code = entity.metric_code
    model.triggered_value = entity.triggered_value
    model.threshold = entity.threshold
    model.operator = entity.operator.value
    model.message = entity.message
    model.status = entity.status.value
    model.error = entity.error
    model.created_at = entity.created_at
