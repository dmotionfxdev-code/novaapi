"""Repository interface — domain layer contract (Application Layer §1: one
repository per aggregate root). Concrete SQLAlchemy implementation lives in
``contexts/reporting/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.value_objects import ReportId


class ReportRepository(Protocol):
    async def get_by_id(self, report_id: ReportId) -> Report | None: ...

    async def get_latest(self, tenant_id: TenantId, assessment_id: str) -> Report | None:
        """The most recent (highest ``version``) report for one
        assessment, regardless of status — a caller inspects ``.status``
        to tell a still-``DRAFT`` latest generation from a ``FINALIZED``
        one."""
        ...

    async def list_by_assessment(self, tenant_id: TenantId, assessment_id: str) -> list[Report]:
        """"Historical snapshots" (Sprint 9) — every generation ever
        produced for this assessment, oldest first."""
        ...

    async def list_latest_by_tenant(self, tenant_id: TenantId) -> list[Report]:
        """"Dashboard Projection Layer" (Sprint 9 requirement #9) — the
        latest report per assessment, across every assessment this tenant
        has. Reporting already captured everything a dashboard needs at
        generation time, so this query never has to reach back into any
        other context."""
        ...

    async def next_version(self, tenant_id: TenantId, assessment_id: str) -> int: ...

    async def save(self, report: Report) -> None:
        """Insert on first save (a brand-new ``DRAFT`` generation);
        update-in-place on every subsequent save of the SAME ``id`` (the
        ``finalize()`` transition) — never a second row for the same
        generation, unlike ``StageResult``/``PredictionRun``'s
        always-insert pattern, since ``DRAFT``/``FINALIZED`` are two
        states of one generation, not two independent computation runs.
        """
        ...
