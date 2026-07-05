"""The three aggregate roots of the Notification & Early Warning context
(Sprint 11 requirements #1-#3).

``AlertRule`` and ``NotificationSubscription`` are long-lived CONFIGURATION
aggregates — mutable, in-place-updated (the same "no direct mutation
outside a named method" discipline every aggregate in this codebase
enforces, but via update-in-place + repository UPDATE, Assessment's
pattern, not a new-version-per-change pattern; a rule/subscription being
edited is the same configuration entity, not a new piece of evidence).
``Notification`` is a one-shot EVIDENCE aggregate (like ``StageResult``/
``PredictionRun``) — built complete, in its final ``SENT``/``FAILED``
state, in a single classmethod call, since channel dispatch here is
synchronous with no async job in between "asked to send" and "done".

Nothing here imports from ``contexts.assessment``/``contexts.analysis``/
``contexts.prediction``/``contexts.validation``/``contexts.reporting`` —
structurally enforced by the import-linter's peer-independence contract;
Notification is a Generic Subdomain, entirely decoupled from hazard-
specific concerns (Domain Model §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.notification.domain.errors import (
    InvalidAlertRuleError,
    InvalidNotificationSubscriptionError,
)
from georisk.contexts.notification.domain.events import (
    AlertRuleActivated,
    AlertRuleCreated,
    AlertRuleDeactivated,
    AlertRuleUpdated,
    NotificationDeliveryFailed,
    NotificationSent,
    NotificationSubscriptionActivated,
    NotificationSubscriptionCreated,
    NotificationSubscriptionDeactivated,
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


@dataclass(slots=True)
class AlertRule:
    id: AlertRuleId
    tenant_id: TenantId
    name: str
    subject_type: AlertSubjectType
    # Optional filter — a rule with ``hazard_type=None`` evaluates against
    # every assessment regardless of hazard type (Sprint 11 requirement:
    # "Support: Flood Alerts, Wildfire Alerts, Prediction Alerts,
    # Validation Alerts" — a Prediction/Validation-subject rule usually
    # has no reason to scope by hazard type at all).
    hazard_type: str | None
    # Required (and only meaningful) when subject_type is STAGE_RESULT —
    # which stage's IndicatorSet to read metric_code from (e.g. "RISK" for
    # the brief's own FRI/WRI examples).
    stage_type: str | None
    metric_code: str
    operator: AlertOperator
    threshold: float
    severity: AlertSeverity
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        tenant_id: TenantId,
        name: str,
        subject_type: AlertSubjectType,
        hazard_type: str | None,
        stage_type: str | None,
        metric_code: str,
        operator: AlertOperator,
        threshold: float,
        severity: AlertSeverity,
        created_by: str,
    ) -> tuple[AlertRule, AlertRuleCreated]:
        if not name.strip():
            raise InvalidAlertRuleError("AlertRule name must not be blank")
        if not metric_code.strip():
            raise InvalidAlertRuleError("AlertRule metric_code must not be blank")
        if subject_type is AlertSubjectType.STAGE_RESULT and not stage_type:
            raise InvalidAlertRuleError(
                "stage_type is required when subject_type is STAGE_RESULT"
            )
        if subject_type is not AlertSubjectType.STAGE_RESULT and stage_type:
            raise InvalidAlertRuleError(
                "stage_type is only meaningful when subject_type is STAGE_RESULT"
            )

        now = datetime.now(UTC)
        rule = cls(
            id=AlertRuleId.new(),
            tenant_id=tenant_id,
            name=name,
            subject_type=subject_type,
            hazard_type=hazard_type,
            stage_type=stage_type,
            metric_code=metric_code,
            operator=operator,
            threshold=threshold,
            severity=severity,
            is_active=True,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        event = AlertRuleCreated(
            alert_rule_id=str(rule.id),
            tenant_id=str(tenant_id),
            name=name,
            subject_type=subject_type.value,
            metric_code=metric_code,
            operator=operator.value,
            threshold=threshold,
            severity=severity.value,
            created_by=created_by,
        )
        return rule, event

    def update_threshold(self, *, threshold: float, changed_by: str) -> AlertRuleUpdated:
        self.threshold = threshold
        self.updated_at = datetime.now(UTC)
        return AlertRuleUpdated(
            alert_rule_id=str(self.id),
            tenant_id=str(self.tenant_id),
            threshold=threshold,
            changed_by=changed_by,
        )

    def activate(self, *, changed_by: str) -> AlertRuleActivated:
        self.is_active = True
        self.updated_at = datetime.now(UTC)
        return AlertRuleActivated(
            alert_rule_id=str(self.id), tenant_id=str(self.tenant_id), changed_by=changed_by
        )

    def deactivate(self, *, changed_by: str) -> AlertRuleDeactivated:
        self.is_active = False
        self.updated_at = datetime.now(UTC)
        return AlertRuleDeactivated(
            alert_rule_id=str(self.id), tenant_id=str(self.tenant_id), changed_by=changed_by
        )


@dataclass(slots=True)
class NotificationSubscription:
    id: NotificationSubscriptionId
    tenant_id: TenantId
    user_id: UserId
    # Optional filter — mirrors AlertRule.hazard_type: None subscribes to
    # every hazard type.
    hazard_type: str | None
    channels: frozenset[NotificationChannelType]
    email_address: str | None
    phone_number: str | None
    is_active: bool
    created_at: datetime

    @classmethod
    def subscribe(
        cls,
        *,
        tenant_id: TenantId,
        user_id: UserId,
        hazard_type: str | None,
        channels: frozenset[NotificationChannelType],
        email_address: str | None,
        phone_number: str | None,
    ) -> tuple[NotificationSubscription, NotificationSubscriptionCreated]:
        if not channels:
            raise InvalidNotificationSubscriptionError(
                "A NotificationSubscription must select at least one channel"
            )
        if NotificationChannelType.EMAIL in channels and not email_address:
            raise InvalidNotificationSubscriptionError(
                "email_address is required when EMAIL is among the selected channels"
            )
        if NotificationChannelType.SMS in channels and not phone_number:
            raise InvalidNotificationSubscriptionError(
                "phone_number is required when SMS is among the selected channels"
            )

        subscription = cls(
            id=NotificationSubscriptionId.new(),
            tenant_id=tenant_id,
            user_id=user_id,
            hazard_type=hazard_type,
            channels=channels,
            email_address=email_address,
            phone_number=phone_number,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        event = NotificationSubscriptionCreated(
            subscription_id=str(subscription.id),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            channels=sorted(c.value for c in channels),
        )
        return subscription, event

    def activate(self, *, changed_by: str) -> NotificationSubscriptionActivated:
        self.is_active = True
        return NotificationSubscriptionActivated(
            subscription_id=str(self.id), tenant_id=str(self.tenant_id), changed_by=changed_by
        )

    def deactivate(self, *, changed_by: str) -> NotificationSubscriptionDeactivated:
        self.is_active = False
        return NotificationSubscriptionDeactivated(
            subscription_id=str(self.id), tenant_id=str(self.tenant_id), changed_by=changed_by
        )


@dataclass(slots=True)
class Notification:
    id: NotificationId
    tenant_id: TenantId
    # Soft, plain-string cross-context reference — assessment is a peer
    # context (import-linter's independence contract).
    assessment_id: str
    # Same-context references — AlertRule/NotificationSubscription are
    # Notification's own aggregates, so these ARE typed ids.
    alert_rule_id: AlertRuleId
    subscription_id: NotificationSubscriptionId
    channel: NotificationChannelType
    recipient: str
    severity: AlertSeverity
    metric_code: str
    triggered_value: float
    threshold: float
    operator: AlertOperator
    message: str
    status: NotificationStatus
    error: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def sent(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        alert_rule_id: AlertRuleId,
        subscription_id: NotificationSubscriptionId,
        channel: NotificationChannelType,
        recipient: str,
        severity: AlertSeverity,
        metric_code: str,
        triggered_value: float,
        threshold: float,
        operator: AlertOperator,
        message: str,
    ) -> tuple[Notification, NotificationSent]:
        notification = cls(
            id=NotificationId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            alert_rule_id=alert_rule_id,
            subscription_id=subscription_id,
            channel=channel,
            recipient=recipient,
            severity=severity,
            metric_code=metric_code,
            triggered_value=triggered_value,
            threshold=threshold,
            operator=operator,
            message=message,
            status=NotificationStatus.SENT,
            error=None,
        )
        event = NotificationSent(
            notification_id=str(notification.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            alert_rule_id=str(alert_rule_id),
            channel=channel.value,
            severity=severity.value,
        )
        return notification, event

    @classmethod
    def failed(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        alert_rule_id: AlertRuleId,
        subscription_id: NotificationSubscriptionId,
        channel: NotificationChannelType,
        recipient: str,
        severity: AlertSeverity,
        metric_code: str,
        triggered_value: float,
        threshold: float,
        operator: AlertOperator,
        message: str,
        error: str,
    ) -> tuple[Notification, NotificationDeliveryFailed]:
        notification = cls(
            id=NotificationId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            alert_rule_id=alert_rule_id,
            subscription_id=subscription_id,
            channel=channel,
            recipient=recipient,
            severity=severity,
            metric_code=metric_code,
            triggered_value=triggered_value,
            threshold=threshold,
            operator=operator,
            message=message,
            status=NotificationStatus.FAILED,
            error=error,
        )
        event = NotificationDeliveryFailed(
            notification_id=str(notification.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            alert_rule_id=str(alert_rule_id),
            channel=channel.value,
            severity=severity.value,
            error=error,
        )
        return notification, event
