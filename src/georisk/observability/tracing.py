"""OpenTelemetry wiring.

Exports to an OTLP collector if ``OTEL_EXPORTER_ENDPOINT`` is configured;
otherwise traces are created but not exported anywhere — sufficient for
local development, where the trace-id-in-logs correlation (via
``observability.logging``) is usually enough on its own.

Trace context is expected to propagate across the outbox/event boundary
once Roadmap Sprint 3 introduces it (Infrastructure Architecture §22) — that
propagation is not implemented here, since no outbox or event bus exists
yet; this module only establishes the SDK and the FastAPI instrumentation
hook every later sprint's spans will attach to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

if TYPE_CHECKING:
    from fastapi import FastAPI

    from georisk.settings import Settings

_configured = False


def configure_tracing(settings: Settings) -> None:
    global _configured
    if _configured:
        return

    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    exporter: OTLPSpanExporter | ConsoleSpanExporter
    if settings.otel_exporter_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True


def shutdown_tracing() -> None:
    """Flushes and stops the tracer provider's background export thread.

    Without this, ``BatchSpanProcessor`` keeps a daemon thread running past
    the app's own shutdown — harmless for a long-lived production process,
    but it produces exactly the kind of "I/O operation on closed file"
    teardown noise seen when running the test suite (the thread tries to
    flush to stdout after pytest has already closed its capture). Called
    from ``api/app.py``'s lifespan shutdown, and should be called from any
    other process lifecycle (e.g. a Celery worker's own shutdown hook) that
    calls ``configure_tracing`` too, once one exists.
    """
    global _configured
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()
    _configured = False


def instrument_app(app: FastAPI) -> None:
    """Attach FastAPI's OpenTelemetry auto-instrumentation. Called from
    ``create_app()`` after ``configure_tracing`` has run.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
