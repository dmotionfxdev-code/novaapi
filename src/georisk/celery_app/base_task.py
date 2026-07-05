"""Common Celery task base class.

No business logic lives here — only the cross-cutting hooks every real task
(from Roadmap Sprint 3 onward) needs regardless of what it does: structured
failure logging tied to the dead-letter pattern Application Layer §10 and
Infrastructure Architecture §11 describe, and trace-id propagation into the
worker process's log lines.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

from georisk.observability.logging import trace_id_var

logger = logging.getLogger("georisk.celery")


class PlatformTask(Task):
    """Base class every real task subclasses starting Roadmap Sprint 3.

    ``autoretry_for`` is deliberately empty here — each task declares its
    own retryable exception set (Application Layer §10 distinguishes
    transient/retryable failures from domain/validation ones that must fail
    fast). **Every subclass must override ``autoretry_for`` explicitly.**
    This is enforced by code-review checklist for now, not by tooling — see
    Sprint 0 Review finding #35 / Remediation #35: automating this is
    deferred until enough real tasks exist (Roadmap Sprint 5+) to justify a
    lint rule over a review checklist.
    """

    autoretry_for: tuple[type[Exception], ...] = ()
    max_retries = 5
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True

    # task_acks_late=True (celery_app/app.py) means a worker crash mid-task
    # causes redelivery. This is only safe because of command-handler
    # idempotency (Application Layer §11) — which does not exist until
    # Roadmap Sprint 2–3. The only tasks that exist in Sprint 0 (the
    # queue-topology smoke tests below) are side-effect-free, so redelivery
    # is harmless regardless; this safety claim must be re-verified once
    # real tasks land, not assumed proven by Sprint 0 (Remediation #15/#20
    # "tracked assumption" note).

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,  # celery.utils.serialization.ExceptionInfo — celery ships no stubs/py.typed
    ) -> None:
        """Minimal, structured failure logging — the seam every real task's
        dead-letter behavior plugs into later (Sprint 0 Review finding #13 /
        Remediation #13). The dead-letter queue/table itself is not built
        here; only the hook every task already has access to.
        """
        logger.error(
            "Task failed permanently",
            extra={
                "task_name": self.name,
                "task_id": task_id,
                "traceId": trace_id_var.get(),
                "args": args,
                "kwargs": kwargs,
                "error": str(exc),
            },
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)
