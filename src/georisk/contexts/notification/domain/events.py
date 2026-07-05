"""Notification domain events — appended to the outbox within the same
transaction as the aggregate they describe (Sprint 11 requirement: audit
verification; matching every prior context's pattern). ``NotificationSent``/
``NotificationDeliveryFailed`` names match Domain Model §1 row 18's event
table (``NotificationDelivered``/``NotificationDeliveryFailed``) almost
exactly — renamed the first to ``NotificationSent`` to match this
context's own ``NotificationStatus.SENT`` vocabulary rather than mixing
"Sent" (status) and "Delivered" (event) for the same fact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class AlertRuleCreated:
    event_type: ClassVar[str] = "notification.AlertRuleCreated"
    alert_rule_id: str
    tenant_id: str
    name: str
    subject_type: str
    metric_code: str
    operator: str
    threshold: float
    severity: str
    created_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AlertRuleUpdated:
    event_type: ClassVar[str] = "notification.AlertRuleUpdated"
    alert_rule_id: str
    tenant_id: str
    threshold: float
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AlertRuleActivated:
    event_type: ClassVar[str] = "notification.AlertRuleActivated"
    alert_rule_id: str
    tenant_id: str
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AlertRuleDeactivated:
    event_type: ClassVar[str] = "notification.AlertRuleDeactivated"
    alert_rule_id: str
    tenant_id: str
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class NotificationSubscriptionCreated:
    event_type: ClassVar[str] = "notification.NotificationSubscriptionCreated"
    subscription_id: str
    tenant_id: str
    user_id: str
    channels: list[str]

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class NotificationSubscriptionActivated:
    event_type: ClassVar[str] = "notification.NotificationSubscriptionActivated"
    subscription_id: str
    tenant_id: str
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class NotificationSubscriptionDeactivated:
    event_type: ClassVar[str] = "notification.NotificationSubscriptionDeactivated"
    subscription_id: str
    tenant_id: str
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class NotificationSent:
    event_type: ClassVar[str] = "notification.NotificationSent"
    notification_id: str
    tenant_id: str
    assessment_id: str
    alert_rule_id: str
    channel: str
    severity: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class NotificationDeliveryFailed:
    event_type: ClassVar[str] = "notification.NotificationDeliveryFailed"
    notification_id: str
    tenant_id: str
    assessment_id: str
    alert_rule_id: str
    channel: str
    severity: str
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
