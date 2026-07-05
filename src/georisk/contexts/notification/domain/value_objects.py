"""Value objects for the Notification & Early Warning context (Domain
Model §1 rows 16-18: `NotificationRule`/`AlertInstance`/
`NotificationDispatch` in the full design — Sprint 11's brief gives its own
concrete aggregate names instead: `AlertRule`, `NotificationSubscription`,
`Notification`, used throughout this context).

Notification is a Generic Subdomain (Domain Model §4): "a notification
reacts to something that already happened; it never decides what
happens." Nothing here references a hazard type, an assessment's internal
fields, a GIS concept, or a prediction/validation concept — `subject_type`/
`metric_code` are generic strings, exactly the same "conformist downstream
reader" discipline Validation (Sprint 4/10) and Reporting (Sprint 9)
already established for their own upstream reads.
"""

from __future__ import annotations

from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class AlertRuleId(TypedId):
    pass


class NotificationSubscriptionId(TypedId):
    pass


class NotificationId(TypedId):
    pass


class AlertSubjectType(StrEnum):
    """What an ``AlertRule`` watches — mirrors Validation's own
    ``SubjectType`` vocabulary (``STAGE_RESULT``/``PREDICTION``) plus
    ``VALIDATION`` (Sprint 11's own "Validation Alerts" requirement,
    Validation's ``ValidationRun`` metrics being a legitimate alert
    subject in its own right, not just something that produces alerts for
    others) — a separate, locally-defined enum, never an import of
    ``contexts.validation.domain.value_objects.SubjectType`` (peer-
    independence contract).
    """

    STAGE_RESULT = "STAGE_RESULT"
    PREDICTION = "PREDICTION"
    VALIDATION = "VALIDATION"


class AlertOperator(StrEnum):
    """"Alert Rules must be configurable" — the comparison an
    ``AlertRule`` applies between the resolved metric value and its
    configured threshold. All four are supported for genuine
    configurability even though the brief's own examples only use two
    (``FRI > threshold``, ``R² < threshold``).
    """

    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"

    def evaluate(self, actual: float, threshold: float) -> bool:
        if self is AlertOperator.GREATER_THAN:
            return actual > threshold
        if self is AlertOperator.LESS_THAN:
            return actual < threshold
        if self is AlertOperator.GREATER_THAN_OR_EQUAL:
            return actual >= threshold
        return actual <= threshold


class AlertSeverity(StrEnum):
    """Sprint 11 requirement #6 — a fixed property of the ``AlertRule``
    itself (configured by whoever authors the rule), not a value computed
    dynamically from how far past the threshold the observed metric is:
    inventing a severity-scoring formula nobody asked for would be
    speculative (the same "don't invent scoring rules" discipline Data
    Acquisition's ``DatasetReadinessTag`` docstring already established in
    Sprint 7). A firing rule's severity is copied onto the resulting
    ``Notification`` at trigger time, frozen there even if the rule's own
    severity is edited later.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NotificationChannelType(StrEnum):
    """Sprint 11 requirements #7/#8/#9."""

    EMAIL = "EMAIL"
    SMS = "SMS"
    IN_APP = "IN_APP"


class NotificationStatus(StrEnum):
    """Deliberately just two terminal states, not a PENDING/SENDING/SENT
    pipeline — channel dispatch here is synchronous with no async job in
    between "asked to send" and "done" (the same reasoning
    ``ValidationRunStatus``/``PredictionRunStatus``/``StageResultStatus``
    each already documented for their own two-state shape)."""

    SENT = "SENT"
    FAILED = "FAILED"
