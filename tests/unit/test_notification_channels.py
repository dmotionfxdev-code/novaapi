"""Unit tests for Notification's channel implementations — no real SMTP
server or SMS gateway is used; these test the honest
unconfigured/unreachable failure paths, which are genuinely real,
deterministic code paths (see ``infrastructure/channels.py``'s module
docstring for why this is the right boundary to test without fabricating
external infrastructure).
"""

from __future__ import annotations

import pytest

from georisk.contexts.notification.application.ports import (
    InAppNotificationChannel,
    UnconfiguredSmsNotificationChannel,
)
from georisk.contexts.notification.infrastructure.channels import SmtpEmailNotificationChannel
from georisk.settings import Settings

pytestmark = pytest.mark.unit


async def test_in_app_channel_always_delivers() -> None:
    channel = InAppNotificationChannel()
    result = await channel.send(recipient="user-1", subject="Alert", message="body")
    assert result.delivered is True
    assert result.error is None


async def test_sms_channel_is_honestly_unconfigured() -> None:
    channel = UnconfiguredSmsNotificationChannel()
    result = await channel.send(recipient="+15551234567", subject="Alert", message="body")
    assert result.delivered is False
    assert result.error == "SMS provider not configured"


async def test_email_channel_without_smtp_host_fails_immediately() -> None:
    settings = Settings(smtp_host=None)
    channel = SmtpEmailNotificationChannel(settings)
    result = await channel.send(recipient="user@example.com", subject="Alert", message="body")
    assert result.delivered is False
    assert result.error == "SMTP not configured"


async def test_email_channel_with_unreachable_host_fails_gracefully() -> None:
    settings = Settings(
        smtp_host="127.0.0.1", smtp_port=59999, smtp_timeout_seconds=1.0
    )
    channel = SmtpEmailNotificationChannel(settings)
    result = await channel.send(recipient="user@example.com", subject="Alert", message="body")
    assert result.delivered is False
    assert result.error is not None
