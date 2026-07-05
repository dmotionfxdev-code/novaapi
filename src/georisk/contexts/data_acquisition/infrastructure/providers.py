"""``HttpAcquisitionProvider`` — the USGS/NASA/Copernicus adapter. Lives
here rather than ``application/ports.py`` because it does real socket
I/O (``requests``, wrapped in ``asyncio.to_thread`` since ``requests`` is
synchronous) — the same "I/O is an infrastructure concern" boundary this
codebase draws everywhere else (Prediction's/Data Acquisition's
SQLAlchemy repositories, Notification's ``SmtpEmailNotificationChannel``).

One generic class, not three provider-specific ones: USGS/NASA/Copernicus
each need per-provider ``base_url``/``api_key`` configuration this
codebase has no verified real endpoint/auth-scheme knowledge for, so
building three classes with invented endpoint paths would fabricate
integration detail nobody asked for. A ``base_url=None`` (the default,
identical to ``settings.smtp_host``) means "not configured": every
``fetch()`` call reports an honest, immediate failure rather than
attempting a request that would only ever fail — both the unconfigured
and the "configured against an unreachable/erroring host" cases are real,
tested code paths; what's untested is only "a live USGS/NASA/Copernicus
endpoint actually returns real data," which no sandboxed validation
environment can exercise without fabricating credentials nobody has.
"""

from __future__ import annotations

import asyncio

import requests

from georisk.contexts.data_acquisition.application.ports import FetchResult, RemoteSensingFetchSpec


class HttpAcquisitionProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str | None,
        api_key: str | None,
        timeout_seconds: float,
    ) -> None:
        self._provider_name = provider_name
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def fetch(
        self,
        *,
        source_reference: str,
        raw_content: bytes | None = None,
        spec: RemoteSensingFetchSpec | None = None,
    ) -> FetchResult:
        base_url = self._base_url
        if not base_url:
            return FetchResult(
                success=False,
                content=None,
                error=f"{self._provider_name} is not configured (no base_url set)",
            )
        try:
            content = await asyncio.to_thread(self._fetch_sync, base_url, source_reference)
            return FetchResult(success=True, content=content, error=None)
        except Exception as exc:  # noqa: BLE001 — an HTTP/socket failure is
            # this provider's own untrusted I/O boundary; reporting it as a
            # graceful failed fetch (not an unhandled exception that would
            # crash the whole pipeline handler) is the same "isolate an
            # untrusted boundary" reasoning ``SmtpEmailNotificationChannel``
            # already applies.
            return FetchResult(success=False, content=None, error=str(exc))

    def _fetch_sync(self, base_url: str, source_reference: str) -> bytes:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        response = requests.get(
            f"{base_url.rstrip('/')}/{source_reference.lstrip('/')}",
            headers=headers,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.content
