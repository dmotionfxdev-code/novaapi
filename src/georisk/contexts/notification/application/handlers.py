"""Command handlers for the Notification & Early Warning context.

``EvaluateAlertRulesHandler`` is the Early Warning Engine (Sprint 11
requirement #5): one transaction, gathering every active tenant-wide
``AlertRule`` applicable to the given assessment's hazard type, resolving
each rule's current metric value via the injected ``AlertMetricReader``,
and — for every rule whose condition is met — fanning out to every
matching, active ``NotificationSubscription``'s subscribed channels,
dispatching through the injected channel map, and persisting one
``Notification`` per (rule × subscription × channel) triple. Every other
handler here is a thin, one-aggregate, one-event command handler, the
same shape every prior context's simple command handlers already use.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.notification.application.commands import (
    ActivateAlertRuleCommand,
    ActivateNotificationSubscriptionCommand,
    CreateAlertRuleCommand,
    CreateNotificationSubscriptionCommand,
    DeactivateAlertRuleCommand,
    DeactivateNotificationSubscriptionCommand,
    EvaluateAlertRulesCommand,
    UpdateAlertRuleThresholdCommand,
)
from georisk.contexts.notification.application.ports import (
    AlertMetricReader,
    AssessmentReader,
    NotificationChannel,
)
from georisk.contexts.notification.domain.entities import (
    AlertRule,
    Notification,
    NotificationSubscription,
)
from georisk.contexts.notification.domain.errors import AlertRuleNotFoundError as _AlertRuleNF
from georisk.contexts.notification.domain.errors import (
    NotificationSubscriptionNotFoundError as _SubscriptionNF,
)
from georisk.contexts.notification.domain.events import (
    NotificationDeliveryFailed,
    NotificationSent,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertOperator,
    AlertRuleId,
    AlertSeverity,
    AlertSubjectType,
    NotificationChannelType,
    NotificationSubscriptionId,
)
from georisk.contexts.notification.infrastructure.repositories import (
    SqlAlchemyAlertRuleRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyNotificationSubscriptionRepository,
)
from georisk.db.outbox_writer import append_event

_OPERATOR_SYMBOLS: dict[AlertOperator, str] = {
    AlertOperator.GREATER_THAN: ">",
    AlertOperator.LESS_THAN: "<",
    AlertOperator.GREATER_THAN_OR_EQUAL: ">=",
    AlertOperator.LESS_THAN_OR_EQUAL: "<=",
}


def _resolve_recipient(
    channel_type: NotificationChannelType, subscription: NotificationSubscription
) -> str | None:
    if channel_type is NotificationChannelType.EMAIL:
        return subscription.email_address
    if channel_type is NotificationChannelType.SMS:
        return subscription.phone_number
    return str(subscription.user_id)


class CreateAlertRuleHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyAlertRuleRepository(session)

    async def handle(self, command: CreateAlertRuleCommand) -> AlertRule:
        tenant_id = TenantId.from_string(command.tenant_id)
        rule, event = AlertRule.create(
            tenant_id=tenant_id,
            name=command.name,
            subject_type=AlertSubjectType(command.subject_type),
            hazard_type=command.hazard_type,
            stage_type=command.stage_type,
            metric_code=command.metric_code,
            operator=AlertOperator(command.operator),
            threshold=command.threshold,
            severity=AlertSeverity(command.severity),
            created_by=command.issued_by,
        )
        await self._repo.save(rule)
        await append_event(
            self._session,
            aggregate_type="AlertRule",
            aggregate_id=str(rule.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return rule


async def _get_owned_rule(
    repo: SqlAlchemyAlertRuleRepository, tenant_id: TenantId, alert_rule_id: str
) -> AlertRule:
    rule = await repo.get_by_id(AlertRuleId.from_string(alert_rule_id))
    if rule is None or rule.tenant_id != tenant_id:
        raise _AlertRuleNF(f"AlertRule {alert_rule_id} not found")
    return rule


class UpdateAlertRuleThresholdHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyAlertRuleRepository(session)

    async def handle(self, command: UpdateAlertRuleThresholdCommand) -> AlertRule:
        tenant_id = TenantId.from_string(command.tenant_id)
        rule = await _get_owned_rule(self._repo, tenant_id, command.alert_rule_id)
        event = rule.update_threshold(threshold=command.threshold, changed_by=command.issued_by)
        await self._repo.save(rule)
        await append_event(
            self._session,
            aggregate_type="AlertRule",
            aggregate_id=str(rule.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return rule


class ActivateAlertRuleHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyAlertRuleRepository(session)

    async def handle(self, command: ActivateAlertRuleCommand) -> AlertRule:
        tenant_id = TenantId.from_string(command.tenant_id)
        rule = await _get_owned_rule(self._repo, tenant_id, command.alert_rule_id)
        event = rule.activate(changed_by=command.issued_by)
        await self._repo.save(rule)
        await append_event(
            self._session,
            aggregate_type="AlertRule",
            aggregate_id=str(rule.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return rule


class DeactivateAlertRuleHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyAlertRuleRepository(session)

    async def handle(self, command: DeactivateAlertRuleCommand) -> AlertRule:
        tenant_id = TenantId.from_string(command.tenant_id)
        rule = await _get_owned_rule(self._repo, tenant_id, command.alert_rule_id)
        event = rule.deactivate(changed_by=command.issued_by)
        await self._repo.save(rule)
        await append_event(
            self._session,
            aggregate_type="AlertRule",
            aggregate_id=str(rule.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return rule


class CreateNotificationSubscriptionHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyNotificationSubscriptionRepository(session)

    async def handle(
        self, command: CreateNotificationSubscriptionCommand
    ) -> NotificationSubscription:
        tenant_id = TenantId.from_string(command.tenant_id)
        subscription, event = NotificationSubscription.subscribe(
            tenant_id=tenant_id,
            user_id=UserId.from_string(command.user_id),
            hazard_type=command.hazard_type,
            channels=frozenset(NotificationChannelType(c) for c in command.channels),
            email_address=command.email_address,
            phone_number=command.phone_number,
        )
        await self._repo.save(subscription)
        await append_event(
            self._session,
            aggregate_type="NotificationSubscription",
            aggregate_id=str(subscription.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return subscription


async def _get_owned_subscription(
    repo: SqlAlchemyNotificationSubscriptionRepository, tenant_id: TenantId, subscription_id: str
) -> NotificationSubscription:
    subscription = await repo.get_by_id(NotificationSubscriptionId.from_string(subscription_id))
    if subscription is None or subscription.tenant_id != tenant_id:
        raise _SubscriptionNF(f"NotificationSubscription {subscription_id} not found")
    return subscription


class ActivateNotificationSubscriptionHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyNotificationSubscriptionRepository(session)

    async def handle(
        self, command: ActivateNotificationSubscriptionCommand
    ) -> NotificationSubscription:
        tenant_id = TenantId.from_string(command.tenant_id)
        subscription = await _get_owned_subscription(
            self._repo, tenant_id, command.subscription_id
        )
        event = subscription.activate(changed_by=command.issued_by)
        await self._repo.save(subscription)
        await append_event(
            self._session,
            aggregate_type="NotificationSubscription",
            aggregate_id=str(subscription.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return subscription


class DeactivateNotificationSubscriptionHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyNotificationSubscriptionRepository(session)

    async def handle(
        self, command: DeactivateNotificationSubscriptionCommand
    ) -> NotificationSubscription:
        tenant_id = TenantId.from_string(command.tenant_id)
        subscription = await _get_owned_subscription(
            self._repo, tenant_id, command.subscription_id
        )
        event = subscription.deactivate(changed_by=command.issued_by)
        await self._repo.save(subscription)
        await append_event(
            self._session,
            aggregate_type="NotificationSubscription",
            aggregate_id=str(subscription.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return subscription


class EvaluateAlertRulesHandler:
    """The Early Warning Engine (Sprint 11 requirement #5)."""

    def __init__(
        self,
        session: AsyncSession,
        assessment_reader: AssessmentReader,
        metric_reader: AlertMetricReader,
        channels: dict[NotificationChannelType, NotificationChannel],
    ) -> None:
        self._session = session
        self._assessment_reader = assessment_reader
        self._metric_reader = metric_reader
        self._channels = channels
        self._rule_repo = SqlAlchemyAlertRuleRepository(session)
        self._subscription_repo = SqlAlchemyNotificationSubscriptionRepository(session)
        self._notification_repo = SqlAlchemyNotificationRepository(session)

    async def handle(self, command: EvaluateAlertRulesCommand) -> list[Notification]:
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment_info = await self._assessment_reader.get_assessment_info(
            tenant_id=command.tenant_id, assessment_id=command.assessment_id
        )
        if assessment_info is None:
            await self._session.commit()
            return []

        rules = await self._rule_repo.list_active_by_tenant(tenant_id)
        applicable_rules = [
            r
            for r in rules
            if r.hazard_type is None or r.hazard_type == assessment_info.hazard_type
        ]

        subscriptions = await self._subscription_repo.list_active_by_tenant(tenant_id)
        matching_subscriptions = [
            s
            for s in subscriptions
            if s.hazard_type is None or s.hazard_type == assessment_info.hazard_type
        ]

        notifications: list[Notification] = []
        for rule in applicable_rules:
            value = await self._metric_reader.get_metric_value(
                tenant_id=command.tenant_id,
                assessment_id=command.assessment_id,
                subject_type=rule.subject_type.value,
                stage_type=rule.stage_type,
                metric_code=rule.metric_code,
            )
            if value is None or not rule.operator.evaluate(value, rule.threshold):
                continue

            message = (
                f"[{rule.severity.value}] {rule.name}: {rule.metric_code} = {value} "
                f"{_OPERATOR_SYMBOLS[rule.operator]} {rule.threshold} "
                f"on assessment '{assessment_info.name}'"
            )
            for subscription in matching_subscriptions:
                for channel_type in subscription.channels:
                    recipient = _resolve_recipient(channel_type, subscription)
                    channel = self._channels.get(channel_type)
                    if recipient is None or channel is None:
                        continue

                    result = await channel.send(
                        recipient=recipient, subject=rule.name, message=message
                    )
                    event: NotificationSent | NotificationDeliveryFailed
                    if result.delivered:
                        notification, event = Notification.sent(
                            tenant_id=tenant_id,
                            assessment_id=command.assessment_id,
                            alert_rule_id=rule.id,
                            subscription_id=subscription.id,
                            channel=channel_type,
                            recipient=recipient,
                            severity=rule.severity,
                            metric_code=rule.metric_code,
                            triggered_value=value,
                            threshold=rule.threshold,
                            operator=rule.operator,
                            message=message,
                        )
                    else:
                        notification, event = Notification.failed(
                            tenant_id=tenant_id,
                            assessment_id=command.assessment_id,
                            alert_rule_id=rule.id,
                            subscription_id=subscription.id,
                            channel=channel_type,
                            recipient=recipient,
                            severity=rule.severity,
                            metric_code=rule.metric_code,
                            triggered_value=value,
                            threshold=rule.threshold,
                            operator=rule.operator,
                            message=message,
                            error=result.error or "delivery failed",
                        )

                    await self._notification_repo.save(notification)
                    await append_event(
                        self._session,
                        aggregate_type="Notification",
                        aggregate_id=str(notification.id),
                        event_type=event.event_type,
                        payload=event.payload(),
                        tenant_id=tenant_id.value,
                    )
                    notifications.append(notification)

        await self._session.commit()
        return notifications
