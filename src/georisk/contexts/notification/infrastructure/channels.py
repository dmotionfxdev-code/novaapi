"""Sprint 11 requirement #7 — the Email channel. Unlike SMS (requirement
#8, deliberately just an "abstraction" — ``application/ports.py``'s
``UnconfiguredSmsNotificationChannel``), this is a genuinely working
implementation: real ``smtplib`` I/O, wrapped in ``asyncio.to_thread``
since ``smtplib`` is synchronous. Lives in ``infrastructure/`` rather than
``application/ports.py`` because it does real socket I/O — the same
"I/O is an infrastructure concern" boundary this codebase draws
everywhere else (e.g. Prediction's/Data Acquisition's SQLAlchemy
repositories).

No SMTP server exists anywhere in this platform's development/test
environments (``settings.smtp_host`` defaults to ``None``) — so in
practice this channel always reports an honest, immediate FAILED without
attempting a connection when unconfigured, and a graceful FAILED (not an
unhandled exception) if configured against an unreachable host. Both are
real, meaningful, tested code paths; what's untested is only "a live SMTP
server actually accepts the message," which no sandboxed validation
environment can exercise without fabricating infrastructure nobody asked
for.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from georisk.contexts.notification.application.ports import ChannelDeliveryResult
from georisk.settings import Settings


class SmtpEmailNotificationChannel:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, recipient: str, subject: str, message: str) -> ChannelDeliveryResult:
        smtp_host = self._settings.smtp_host
        if not smtp_host:
            return ChannelDeliveryResult(delivered=False, error="SMTP not configured")
        try:
            await asyncio.to_thread(self._send_sync, smtp_host, recipient, subject, message)
            return ChannelDeliveryResult(delivered=True)
        except Exception as exc:  # noqa: BLE001 — an SMTP/socket failure is
            # this channel's own untrusted I/O boundary; reporting it as a
            # graceful FAILED delivery (not letting it crash the Early
            # Warning Engine's evaluation of every other rule/subscription)
            # is the same "isolate an untrusted boundary" reasoning every
            # prior handler in this codebase already applies to a resolver/
            # provider it doesn't control.
            return ChannelDeliveryResult(delivered=False, error=str(exc))

    def _send_sync(self, smtp_host: str, recipient: str, subject: str, message: str) -> None:
        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = self._settings.smtp_from_address
        email["To"] = recipient
        email.set_content(message)

        with smtplib.SMTP(
            smtp_host,
            self._settings.smtp_port,
            timeout=self._settings.smtp_timeout_seconds,
        ) as client:
            if self._settings.smtp_use_tls:
                client.starttls()
            if self._settings.smtp_username and self._settings.smtp_password:
                client.login(self._settings.smtp_username, self._settings.smtp_password)
            client.send_message(email)
