"""Notification & Early Warning API. ``alert_rule_router``/
``subscription_router`` are top-level catalog surfaces (like Data
Acquisition's, API Resource Model §20's "reference, not owned" shape) —
``AlertRule``/``NotificationSubscription`` are tenant-wide configuration,
not assessment-nested. ``notification_router`` nests the Early Warning
Engine's trigger and per-assessment history under
``/assessments/{assessment_id}/notifications`` purely as a URL-path
convenience (matching Prediction's/Validation's precedent);
``notification_history_router`` is the tenant-wide "Notification History"
surface (requirement #4), mirroring Reporting's ``/dashboard/reports``
shape. None of these routers import anything from ``contexts.assessment``,
``contexts.analysis``, ``contexts.prediction``, or ``contexts.validation``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
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
from georisk.contexts.notification.application.handlers import (
    ActivateAlertRuleHandler,
    ActivateNotificationSubscriptionHandler,
    CreateAlertRuleHandler,
    CreateNotificationSubscriptionHandler,
    DeactivateAlertRuleHandler,
    DeactivateNotificationSubscriptionHandler,
    EvaluateAlertRulesHandler,
    UpdateAlertRuleThresholdHandler,
)
from georisk.contexts.notification.application.ports import (
    AlertMetricReader,
    AssessmentReader,
    NotificationChannel,
)
from georisk.contexts.notification.application.queries import (
    GetAlertRuleQuery,
    GetNotificationSubscriptionQuery,
    ListAlertRulesQuery,
    ListNotificationsByAssessmentQuery,
    ListNotificationsByTenantParams,
    ListNotificationsByTenantQuery,
    ListNotificationSubscriptionsQuery,
)
from georisk.contexts.notification.domain.value_objects import (
    AlertRuleId,
    NotificationChannelType,
    NotificationSubscriptionId,
)
from georisk.contexts.notification.interface.schemas import (
    AlertRuleListResponse,
    AlertRuleResponse,
    CreateAlertRuleRequest,
    CreateNotificationSubscriptionRequest,
    NotificationHistoryPageResponse,
    NotificationListResponse,
    NotificationSubscriptionListResponse,
    NotificationSubscriptionResponse,
    UpdateAlertRuleThresholdRequest,
)
from georisk.db.session import get_session

alert_rule_router = APIRouter(prefix="/alert-rules", tags=["notification"])
subscription_router = APIRouter(prefix="/notification-subscriptions", tags=["notification"])
notification_router = APIRouter(
    prefix="/assessments/{assessment_id}/notifications", tags=["notification"]
)
notification_history_router = APIRouter(prefix="/notifications", tags=["notification"])


def get_assessment_reader(request: Request) -> AssessmentReader:
    return request.app.state.notification_assessment_reader


def get_alert_metric_reader(request: Request) -> AlertMetricReader:
    return request.app.state.notification_alert_metric_reader


def get_notification_channels(
    request: Request,
) -> dict[NotificationChannelType, NotificationChannel]:
    return request.app.state.notification_channels


# --- AlertRule -------------------------------------------------------------


@alert_rule_router.post("", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    body: CreateAlertRuleRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ALERT_RULE_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    handler = CreateAlertRuleHandler(session)
    rule = await handler.handle(
        CreateAlertRuleCommand(
            tenant_id=str(claims.tenant_id),
            name=body.name,
            subject_type=body.subject_type,
            hazard_type=body.hazard_type,
            stage_type=body.stage_type,
            metric_code=body.metric_code,
            operator=body.operator,
            threshold=body.threshold,
            severity=body.severity,
            issued_by=str(claims.user_id),
        )
    )
    return AlertRuleResponse.from_domain(rule)


@alert_rule_router.get("", response_model=AlertRuleListResponse)
async def list_alert_rules(
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ALERT_RULE_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleListResponse:
    rules = await ListAlertRulesQuery(session).handle(claims.tenant_id)
    return AlertRuleListResponse.from_domain(rules)


@alert_rule_router.get("/{alert_rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    alert_rule_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ALERT_RULE_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    rule = await GetAlertRuleQuery(session).handle(
        claims.tenant_id, AlertRuleId.from_string(alert_rule_id)
    )
    return AlertRuleResponse.from_domain(rule)


@alert_rule_router.post(
    "/{alert_rule_id}/actions/update-threshold", response_model=AlertRuleResponse
)
async def update_alert_rule_threshold(
    alert_rule_id: str,
    body: UpdateAlertRuleThresholdRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ALERT_RULE_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    handler = UpdateAlertRuleThresholdHandler(session)
    rule = await handler.handle(
        UpdateAlertRuleThresholdCommand(
            tenant_id=str(claims.tenant_id),
            alert_rule_id=alert_rule_id,
            threshold=body.threshold,
            issued_by=str(claims.user_id),
        )
    )
    return AlertRuleResponse.from_domain(rule)


@alert_rule_router.post("/{alert_rule_id}/actions/activate", response_model=AlertRuleResponse)
async def activate_alert_rule(
    alert_rule_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ALERT_RULE_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    handler = ActivateAlertRuleHandler(session)
    rule = await handler.handle(
        ActivateAlertRuleCommand(
            tenant_id=str(claims.tenant_id),
            alert_rule_id=alert_rule_id,
            issued_by=str(claims.user_id),
        )
    )
    return AlertRuleResponse.from_domain(rule)


@alert_rule_router.post("/{alert_rule_id}/actions/deactivate", response_model=AlertRuleResponse)
async def deactivate_alert_rule(
    alert_rule_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ALERT_RULE_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    handler = DeactivateAlertRuleHandler(session)
    rule = await handler.handle(
        DeactivateAlertRuleCommand(
            tenant_id=str(claims.tenant_id),
            alert_rule_id=alert_rule_id,
            issued_by=str(claims.user_id),
        )
    )
    return AlertRuleResponse.from_domain(rule)


# --- NotificationSubscription -----------------------------------------------


@subscription_router.post("", response_model=NotificationSubscriptionResponse, status_code=201)
async def create_notification_subscription(
    body: CreateNotificationSubscriptionRequest,
    claims: Annotated[
        AccessTokenClaims,
        Depends(require_permission(PermissionCode.NOTIFICATION_SUBSCRIPTION_MANAGE)),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSubscriptionResponse:
    """Self-service — a caller always subscribes themselves
    (``claims.user_id``), never another user; there is no body field for
    ``user_id``."""
    handler = CreateNotificationSubscriptionHandler(session)
    subscription = await handler.handle(
        CreateNotificationSubscriptionCommand(
            tenant_id=str(claims.tenant_id),
            user_id=str(claims.user_id),
            hazard_type=body.hazard_type,
            channels=tuple(body.channels),
            email_address=body.email_address,
            phone_number=body.phone_number,
        )
    )
    return NotificationSubscriptionResponse.from_domain(subscription)


@subscription_router.get("", response_model=NotificationSubscriptionListResponse)
async def list_notification_subscriptions(
    claims: Annotated[
        AccessTokenClaims,
        Depends(require_permission(PermissionCode.NOTIFICATION_SUBSCRIPTION_VIEW)),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSubscriptionListResponse:
    subscriptions = await ListNotificationSubscriptionsQuery(session).handle(claims.tenant_id)
    return NotificationSubscriptionListResponse.from_domain(subscriptions)


@subscription_router.get("/{subscription_id}", response_model=NotificationSubscriptionResponse)
async def get_notification_subscription(
    subscription_id: str,
    claims: Annotated[
        AccessTokenClaims,
        Depends(require_permission(PermissionCode.NOTIFICATION_SUBSCRIPTION_VIEW)),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSubscriptionResponse:
    subscription = await GetNotificationSubscriptionQuery(session).handle(
        claims.tenant_id, NotificationSubscriptionId.from_string(subscription_id)
    )
    return NotificationSubscriptionResponse.from_domain(subscription)


@subscription_router.post(
    "/{subscription_id}/actions/activate", response_model=NotificationSubscriptionResponse
)
async def activate_notification_subscription(
    subscription_id: str,
    claims: Annotated[
        AccessTokenClaims,
        Depends(require_permission(PermissionCode.NOTIFICATION_SUBSCRIPTION_MANAGE)),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSubscriptionResponse:
    handler = ActivateNotificationSubscriptionHandler(session)
    subscription = await handler.handle(
        ActivateNotificationSubscriptionCommand(
            tenant_id=str(claims.tenant_id),
            subscription_id=subscription_id,
            issued_by=str(claims.user_id),
        )
    )
    return NotificationSubscriptionResponse.from_domain(subscription)


@subscription_router.post(
    "/{subscription_id}/actions/deactivate", response_model=NotificationSubscriptionResponse
)
async def deactivate_notification_subscription(
    subscription_id: str,
    claims: Annotated[
        AccessTokenClaims,
        Depends(require_permission(PermissionCode.NOTIFICATION_SUBSCRIPTION_MANAGE)),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSubscriptionResponse:
    handler = DeactivateNotificationSubscriptionHandler(session)
    subscription = await handler.handle(
        DeactivateNotificationSubscriptionCommand(
            tenant_id=str(claims.tenant_id),
            subscription_id=subscription_id,
            issued_by=str(claims.user_id),
        )
    )
    return NotificationSubscriptionResponse.from_domain(subscription)


# --- Notification / Early Warning Engine ------------------------------------


@notification_router.post("/actions/evaluate-alert-rules", response_model=NotificationListResponse)
async def evaluate_alert_rules(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.NOTIFICATION_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    assessment_reader: Annotated[AssessmentReader, Depends(get_assessment_reader)],
    metric_reader: Annotated[AlertMetricReader, Depends(get_alert_metric_reader)],
    channels: Annotated[
        dict[NotificationChannelType, NotificationChannel], Depends(get_notification_channels)
    ],
) -> NotificationListResponse:
    handler = EvaluateAlertRulesHandler(session, assessment_reader, metric_reader, channels)
    notifications = await handler.handle(
        EvaluateAlertRulesCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            issued_by=str(claims.user_id),
        )
    )
    return NotificationListResponse.from_domain(notifications)


@notification_router.get("", response_model=NotificationListResponse)
async def list_notifications_for_assessment(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.NOTIFICATION_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationListResponse:
    notifications = await ListNotificationsByAssessmentQuery(session).handle(
        claims.tenant_id, assessment_id
    )
    return NotificationListResponse.from_domain(notifications)


@notification_history_router.get("", response_model=NotificationHistoryPageResponse)
async def list_notification_history(
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.NOTIFICATION_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> NotificationHistoryPageResponse:
    page = await ListNotificationsByTenantQuery(session).handle(
        ListNotificationsByTenantParams(tenant_id=claims.tenant_id, limit=limit, cursor=cursor)
    )
    return NotificationHistoryPageResponse.from_page(page)
