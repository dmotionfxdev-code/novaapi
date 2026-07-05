"""Handler-level integration tests against a real Postgres instance —
``EvaluateAlertRulesHandler`` (the Early Warning Engine)'s gather ->
evaluate -> dispatch -> persist -> emit-events pipeline. Uses fake
``AssessmentReader``/``AlertMetricReader``/``NotificationChannel``
implementations (not the real composition-root ones, which need a
genuine Assessment/Analysis/Prediction/Validation stack — proven
separately in ``test_notification_api.py``'s live-HTTP test) so this file
can exercise the engine's own fan-out/filtering logic in isolation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.notification.application.commands import EvaluateAlertRulesCommand
from georisk.contexts.notification.application.handlers import EvaluateAlertRulesHandler
from georisk.contexts.notification.application.ports import AssessmentInfo, ChannelDeliveryResult
from georisk.contexts.notification.domain.entities import AlertRule, NotificationSubscription
from georisk.contexts.notification.domain.value_objects import (
    AlertOperator,
    AlertSeverity,
    AlertSubjectType,
    NotificationChannelType,
    NotificationStatus,
)
from georisk.contexts.notification.infrastructure.repositories import (
    SqlAlchemyAlertRuleRepository,
    SqlAlchemyNotificationSubscriptionRepository,
)
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


class _FakeAssessmentReader:
    def __init__(self, info: AssessmentInfo | None) -> None:
        self._info = info

    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None:
        return self._info


class _FakeAlertMetricReader:
    def __init__(self, values: dict[tuple[str, str], float]) -> None:
        self._values = values

    async def get_metric_value(
        self, *, tenant_id, assessment_id, subject_type, stage_type, metric_code  # noqa: ANN001
    ) -> float | None:
        return self._values.get((subject_type, metric_code))


class _FakeChannel:
    def __init__(self, *, delivered: bool = True, error: str | None = None) -> None:
        self._delivered = delivered
        self._error = error
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, *, recipient: str, subject: str, message: str) -> ChannelDeliveryResult:
        self.sent.append((recipient, subject, message))
        return ChannelDeliveryResult(delivered=self._delivered, error=self._error)


async def _create_rule(
    session,  # noqa: ANN001
    tenant_id: TenantId,
    *,
    subject_type: AlertSubjectType,
    metric_code: str,
    operator: AlertOperator,
    threshold: float,
    hazard_type: str | None = None,
    stage_type: str | None = None,
    severity: AlertSeverity = AlertSeverity.HIGH,
) -> AlertRule:
    rule, _event = AlertRule.create(
        tenant_id=tenant_id,
        name=f"{metric_code} rule",
        subject_type=subject_type,
        hazard_type=hazard_type,
        stage_type=stage_type,
        metric_code=metric_code,
        operator=operator,
        threshold=threshold,
        severity=severity,
        created_by="analyst-1",
    )
    await SqlAlchemyAlertRuleRepository(session).save(rule)
    return rule


async def _create_subscription(
    session,  # noqa: ANN001
    tenant_id: TenantId,
    *,
    channels: frozenset[NotificationChannelType],
    hazard_type: str | None = None,
    email_address: str | None = None,
) -> NotificationSubscription:
    subscription, _event = NotificationSubscription.subscribe(
        tenant_id=tenant_id,
        user_id=UserId.new(),
        hazard_type=hazard_type,
        channels=channels,
        email_address=email_address,
        phone_number=None,
    )
    await SqlAlchemyNotificationSubscriptionRepository(session).save(subscription)
    return subscription


async def test_stage_result_rule_fires_and_sends_in_app_notification(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.STAGE_RESULT,
        metric_code="flood_risk_index",
        operator=AlertOperator.GREATER_THAN,
        threshold=0.5,
        hazard_type="FLOOD",
        stage_type="RISK",
    )
    await _create_subscription(
        db_session, tenant_id, channels=frozenset({NotificationChannelType.IN_APP})
    )
    await db_session.flush()

    in_app = _FakeChannel(delivered=True)
    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "FLOOD")),
        _FakeAlertMetricReader({("STAGE_RESULT", "flood_risk_index"): 0.72}),
        {NotificationChannelType.IN_APP: in_app},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )

    assert len(notifications) == 1
    assert notifications[0].status == NotificationStatus.SENT
    assert notifications[0].triggered_value == 0.72
    assert len(in_app.sent) == 1

    outbox = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_type == "Notification")
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert "notification.NotificationSent" in event_types


async def test_rule_does_not_fire_when_condition_not_met(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.STAGE_RESULT,
        metric_code="flood_risk_index",
        operator=AlertOperator.GREATER_THAN,
        threshold=0.5,
        hazard_type="FLOOD",
        stage_type="RISK",
    )
    await _create_subscription(
        db_session, tenant_id, channels=frozenset({NotificationChannelType.IN_APP})
    )
    await db_session.flush()

    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "FLOOD")),
        _FakeAlertMetricReader({("STAGE_RESULT", "flood_risk_index"): 0.2}),
        {NotificationChannelType.IN_APP: _FakeChannel()},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    assert notifications == []


async def test_prediction_and_validation_rules_fire(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.PREDICTION,
        metric_code="rmse",
        operator=AlertOperator.GREATER_THAN,
        threshold=5.0,
    )
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.VALIDATION,
        metric_code="r_squared",
        operator=AlertOperator.LESS_THAN,
        threshold=0.5,
        severity=AlertSeverity.CRITICAL,
    )
    await _create_subscription(
        db_session, tenant_id, channels=frozenset({NotificationChannelType.IN_APP})
    )
    await db_session.flush()

    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "WILDFIRE")),
        _FakeAlertMetricReader(
            {("PREDICTION", "rmse"): 7.2, ("VALIDATION", "r_squared"): 0.3}
        ),
        {NotificationChannelType.IN_APP: _FakeChannel()},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    assert len(notifications) == 2
    severities = {n.severity for n in notifications}
    assert AlertSeverity.CRITICAL in severities


async def test_hazard_type_filters_which_rules_and_subscriptions_apply(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.STAGE_RESULT,
        metric_code="wildfire_risk_index",
        operator=AlertOperator.GREATER_THAN,
        threshold=0.5,
        hazard_type="WILDFIRE",
        stage_type="RISK",
    )
    await _create_subscription(
        db_session, tenant_id, channels=frozenset({NotificationChannelType.IN_APP})
    )
    await db_session.flush()

    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "FLOOD")),
        _FakeAlertMetricReader({("STAGE_RESULT", "wildfire_risk_index"): 0.9}),
        {NotificationChannelType.IN_APP: _FakeChannel()},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    # The rule is scoped to WILDFIRE but the assessment is FLOOD — never
    # evaluated at all, regardless of what the metric reader would return.
    assert notifications == []


async def test_fans_out_to_every_subscribed_channel(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.PREDICTION,
        metric_code="rmse",
        operator=AlertOperator.GREATER_THAN,
        threshold=5.0,
    )
    await _create_subscription(
        db_session,
        tenant_id,
        channels=frozenset({NotificationChannelType.IN_APP, NotificationChannelType.EMAIL}),
        email_address="ops@example.com",
    )
    await db_session.flush()

    in_app = _FakeChannel(delivered=True)
    email = _FakeChannel(delivered=True)
    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "FLOOD")),
        _FakeAlertMetricReader({("PREDICTION", "rmse"): 9.0}),
        {NotificationChannelType.IN_APP: in_app, NotificationChannelType.EMAIL: email},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    assert len(notifications) == 2
    channels_used = {n.channel for n in notifications}
    assert channels_used == {NotificationChannelType.IN_APP, NotificationChannelType.EMAIL}
    assert len(in_app.sent) == 1
    assert len(email.sent) == 1


async def test_failed_channel_delivery_persists_failed_notification(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.PREDICTION,
        metric_code="rmse",
        operator=AlertOperator.GREATER_THAN,
        threshold=5.0,
    )
    await _create_subscription(
        db_session,
        tenant_id,
        channels=frozenset({NotificationChannelType.EMAIL}),
        email_address="ops@example.com",
    )
    await db_session.flush()

    failing_email = _FakeChannel(delivered=False, error="SMTP not configured")
    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "FLOOD")),
        _FakeAlertMetricReader({("PREDICTION", "rmse"): 9.0}),
        {NotificationChannelType.EMAIL: failing_email},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    assert len(notifications) == 1
    assert notifications[0].status == NotificationStatus.FAILED
    assert notifications[0].error == "SMTP not configured"

    outbox = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_type == "Notification")
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert "notification.NotificationDeliveryFailed" in event_types


async def test_inactive_rule_and_subscription_are_skipped(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    rule = await _create_rule(
        db_session,
        tenant_id,
        subject_type=AlertSubjectType.PREDICTION,
        metric_code="rmse",
        operator=AlertOperator.GREATER_THAN,
        threshold=5.0,
    )
    rule.deactivate(changed_by="analyst-1")
    await SqlAlchemyAlertRuleRepository(db_session).save(rule)
    await _create_subscription(
        db_session, tenant_id, channels=frozenset({NotificationChannelType.IN_APP})
    )
    await db_session.flush()

    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(AssessmentInfo(assessment_id, "Test", "FLOOD")),
        _FakeAlertMetricReader({("PREDICTION", "rmse"): 9.0}),
        {NotificationChannelType.IN_APP: _FakeChannel()},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    assert notifications == []


async def test_returns_empty_when_assessment_not_found(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    handler = EvaluateAlertRulesHandler(
        db_session,
        _FakeAssessmentReader(None),
        _FakeAlertMetricReader({}),
        {NotificationChannelType.IN_APP: _FakeChannel()},
    )
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(tenant_id), assessment_id=str(uuid.uuid4()), issued_by="analyst-1"
        )
    )
    assert notifications == []
