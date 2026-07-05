"""Ports the Notification context needs from its peers and from the
outside world:

- ``AssessmentReader``/``AlertMetricReader`` are the "Open Host Service"
  seam into Assessment/Analysis/Prediction/Validation — given an
  assessment and an ``AlertRule``'s ``(subject_type, stage_type,
  metric_code)``, resolve the current metric value to compare against the
  rule's threshold. A composition-root module (``api/notification_ports.py``,
  outside every context involved) implements these by calling each
  upstream context's own repository directly — the same "conformist
  downstream reader" pattern Reporting (Sprint 9) and Validation's
  regression extension (Sprint 10) already established. Deliberately an
  ON-DEMAND EVALUATION seam, not a live subscription to the Domain Event
  Catalog the fuller design (Domain Model §7) describes ("Notification has
  no calls-in... its only coupling ... is the Domain Event Catalog"): no
  outbox relay/consumer exists anywhere in this platform yet (every prior
  sprint's "audit trail" is verified by direct query, never actually
  relayed), so building one exclusively for this sprint would be
  disproportionate scope creep — a deliberate, documented deferral, not a
  silent gap.

- ``NotificationChannel`` is Sprint 11 requirements #7/#8/#9's shared
  delivery abstraction. ``InAppNotificationChannel`` here is genuinely
  real (delivery IS persistence — the notification is already stored by
  the time a channel is asked to "send" it, so there's nothing further to
  do but confirm). ``UnconfiguredSmsNotificationChannel`` is requirement
  #8's honest "abstraction, not a real gateway" placeholder — this
  platform has never integrated an SMS provider (Twilio et al.) anywhere,
  and fabricating one nobody asked for would be speculative; it reports
  every send as not-configured rather than pretending to deliver. The
  real, working Email channel (requirement #7 — deliberately NOT called
  an "abstraction" the way SMS is) lives in
  ``infrastructure/channels.py`` instead, since it does real socket I/O
  (``smtplib``) and infrastructure is where I/O belongs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AssessmentInfo:
    assessment_id: str
    name: str
    hazard_type: str


class AssessmentReader(Protocol):
    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None: ...


class AlertMetricReader(Protocol):
    async def get_metric_value(
        self,
        *,
        tenant_id: str,
        assessment_id: str,
        subject_type: str,
        stage_type: str | None,
        metric_code: str,
    ) -> float | None:
        """The current value of ``metric_code`` for this assessment, under
        the given ``subject_type`` (``STAGE_RESULT`` reads the latest
        COMPLETE ``StageResult`` for ``stage_type``'s ``IndicatorSet``;
        ``PREDICTION`` reads the latest COMPLETED ``PredictionRun``'s
        regression fit; ``VALIDATION`` reads the latest COMPLETED
        ``ValidationRun``'s classification or regression metrics,
        whichever is populated) — ``None`` if no such evidence exists yet
        or the metric isn't present on it, which the Early Warning Engine
        treats as "this rule doesn't fire this round," never an error.
        """
        ...


@dataclass(frozen=True, slots=True)
class ChannelDeliveryResult:
    delivered: bool
    error: str | None = None


class NotificationChannel(Protocol):
    async def send(
        self, *, recipient: str, subject: str, message: str
    ) -> ChannelDeliveryResult: ...


class InAppNotificationChannel:
    """Requirement #9 — genuinely real: an in-app notification's
    "delivery" is exactly the ``Notification`` row already persisted by
    the caller; this channel only confirms that fact."""

    async def send(self, *, recipient: str, subject: str, message: str) -> ChannelDeliveryResult:
        return ChannelDeliveryResult(delivered=True)


class UnconfiguredSmsNotificationChannel:
    """Requirement #8 — "SMS Channel abstraction": the Protocol above IS
    the abstraction; this is its only implementation, and it's honest
    about not being backed by a real SMS gateway."""

    async def send(self, *, recipient: str, subject: str, message: str) -> ChannelDeliveryResult:
        return ChannelDeliveryResult(delivered=False, error="SMS provider not configured")
