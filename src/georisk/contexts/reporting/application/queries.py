"""Query handlers — read-only, never mutate, never go through the command
pipeline (Application Layer §3/§4). Same pattern as every prior context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.errors import ReportNotFoundError
from georisk.contexts.reporting.domain.value_objects import ReportId
from georisk.contexts.reporting.infrastructure.repositories import SqlAlchemyReportRepository


class GetReportQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, report_id: ReportId) -> Report:
        report = await SqlAlchemyReportRepository(self._session).get_by_id(report_id)
        if report is None or report.tenant_id != tenant_id:
            raise ReportNotFoundError(f"Report {report_id} not found")
        return report


class GetLatestReportQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> Report:
        report = await SqlAlchemyReportRepository(self._session).get_latest(
            tenant_id, assessment_id
        )
        if report is None:
            raise ReportNotFoundError(f"No report exists yet for assessment {assessment_id}")
        return report


class ListReportsByAssessmentQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> list[Report]:
        return await SqlAlchemyReportRepository(self._session).list_by_assessment(
            tenant_id, assessment_id
        )


class ListDashboardProjectionsQuery:
    """"Dashboard Projection Layer" (Sprint 9 requirement #9) — the latest
    report per assessment for a tenant, read directly from Reporting's own
    stored snapshots (no cross-context fan-out at query time; see
    ``domain/repositories.py``'s ``list_latest_by_tenant`` docstring)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId) -> list[Report]:
        return await SqlAlchemyReportRepository(self._session).list_latest_by_tenant(tenant_id)
