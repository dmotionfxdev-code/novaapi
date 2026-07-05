from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateAlertRuleCommand:
    tenant_id: str
    name: str
    subject_type: str
    hazard_type: str | None
    stage_type: str | None
    metric_code: str
    operator: str
    threshold: float
    severity: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class UpdateAlertRuleThresholdCommand:
    tenant_id: str
    alert_rule_id: str
    threshold: float
    issued_by: str


@dataclass(frozen=True, slots=True)
class ActivateAlertRuleCommand:
    tenant_id: str
    alert_rule_id: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class DeactivateAlertRuleCommand:
    tenant_id: str
    alert_rule_id: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class CreateNotificationSubscriptionCommand:
    tenant_id: str
    user_id: str
    hazard_type: str | None
    channels: tuple[str, ...]
    email_address: str | None
    phone_number: str | None


@dataclass(frozen=True, slots=True)
class ActivateNotificationSubscriptionCommand:
    tenant_id: str
    subscription_id: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class DeactivateNotificationSubscriptionCommand:
    tenant_id: str
    subscription_id: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class EvaluateAlertRulesCommand:
    """The Early Warning Engine's trigger (Sprint 11 requirement #5) —
    evaluates every active ``AlertRule`` for this tenant against
    ``assessment_id``'s current metric values, firing a ``Notification``
    per (triggered rule × matching subscription × subscribed channel)."""

    tenant_id: str
    assessment_id: str
    issued_by: str
