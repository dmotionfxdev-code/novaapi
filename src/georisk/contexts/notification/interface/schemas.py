"""Pydantic request/response models — independent of the SQLAlchemy models
and domain entities (Architecture Redesign §9). Same pattern as every
prior context.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.shared_kernel.types import CursorPage


class CreateAlertRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject_type: str
    hazard_type: str | None = None
    stage_type: str | None = None
    metric_code: str = Field(min_length=1, max_length=100)
    operator: str
    threshold: float
    severity: str


class UpdateAlertRuleThresholdRequest(BaseModel):
    threshold: float


class AlertRuleResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    subject_type: str
    hazard_type: str | None
    stage_type: str | None
    metric_code: str
    operator: str
    threshold: float
    severity: str
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, rule: AlertRule) -> AlertRuleResponse:
        return cls(
            id=str(rule.id),
            tenant_id=str(rule.tenant_id),
            name=rule.name,
            subject_type=rule.subject_type.value,
            hazard_type=rule.hazard_type,
            stage_type=rule.stage_type,
            metric_code=rule.metric_code,
            operator=rule.operator.value,
            threshold=rule.threshold,
            severity=rule.severity.value,
            is_active=rule.is_active,
            created_by=rule.created_by,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


class AlertRuleListResponse(BaseModel):
    data: list[AlertRuleResponse]

    @classmethod
    def from_domain(cls, rules: list[AlertRule]) -> AlertRuleListResponse:
        return cls(data=[AlertRuleResponse.from_domain(r) for r in rules])


class CreateNotificationSubscriptionRequest(BaseModel):
    hazard_type: str | None = None
    channels: list[str] = Field(min_length=1)
    email_address: str | None = None
    phone_number: str | None = None


class NotificationSubscriptionResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    hazard_type: str | None
    channels: list[str]
    email_address: str | None
    phone_number: str | None
    is_active: bool
    created_at: datetime

    @classmethod
    def from_domain(
        cls, subscription: NotificationSubscription
    ) -> NotificationSubscriptionResponse:
        return cls(
            id=str(subscription.id),
            tenant_id=str(subscription.tenant_id),
            user_id=str(subscription.user_id),
            hazard_type=subscription.hazard_type,
            channels=sorted(c.value for c in subscription.channels),
            email_address=subscription.email_address,
            phone_number=subscription.phone_number,
            is_active=subscription.is_active,
            created_at=subscription.created_at,
        )


class NotificationSubscriptionListResponse(BaseModel):
    data: list[NotificationSubscriptionResponse]

    @classmethod
    def from_domain(
        cls, subscriptions: list[NotificationSubscription]
    ) -> NotificationSubscriptionListResponse:
        return cls(data=[NotificationSubscriptionResponse.from_domain(s) for s in subscriptions])


class NotificationResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    alert_rule_id: str
    subscription_id: str
    channel: str
    recipient: str
    severity: str
    metric_code: str
    triggered_value: float
    threshold: float
    operator: str
    message: str
    status: str
    error: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, notification: Notification) -> NotificationResponse:
        return cls(
            id=str(notification.id),
            tenant_id=str(notification.tenant_id),
            assessment_id=notification.assessment_id,
            alert_rule_id=str(notification.alert_rule_id),
            subscription_id=str(notification.subscription_id),
            channel=notification.channel.value,
            recipient=notification.recipient,
            severity=notification.severity.value,
            metric_code=notification.metric_code,
            triggered_value=notification.triggered_value,
            threshold=notification.threshold,
            operator=notification.operator.value,
            message=notification.message,
            status=notification.status.value,
            error=notification.error,
            created_at=notification.created_at,
        )


class NotificationListResponse(BaseModel):
    data: list[NotificationResponse]

    @classmethod
    def from_domain(cls, notifications: list[Notification]) -> NotificationListResponse:
        return cls(data=[NotificationResponse.from_domain(n) for n in notifications])


class NotificationHistoryPageResponse(BaseModel):
    data: list[NotificationResponse]
    next_cursor: str | None
    has_more: bool

    @classmethod
    def from_page(cls, page: CursorPage[Notification]) -> NotificationHistoryPageResponse:
        return cls(
            data=[NotificationResponse.from_domain(n) for n in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        )
