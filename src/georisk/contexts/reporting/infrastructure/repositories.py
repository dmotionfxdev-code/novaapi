"""Concrete SQLAlchemy repository implementing
``contexts/reporting/domain/repositories.ReportRepository``. Insert on
first save, update-in-place thereafter (see the Protocol's ``save``
docstring for why this differs from ``StageResult``/``PredictionRun``'s
always-insert pattern).
"""

from __future__ import annotations

import uuid as uuid_module

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.value_objects import ReportId
from georisk.contexts.reporting.infrastructure import mappers
from georisk.contexts.reporting.infrastructure.models import ReportModel


class SqlAlchemyReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, report_id: ReportId) -> Report | None:
        model = await self._session.get(ReportModel, report_id.value)
        return mappers.report_to_domain(model) if model else None

    async def get_latest(self, tenant_id: TenantId, assessment_id: str) -> Report | None:
        query = (
            select(ReportModel)
            .where(
                ReportModel.tenant_id == tenant_id.value,
                ReportModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(ReportModel.version.desc())
            .limit(1)
        )
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return mappers.report_to_domain(model) if model else None

    async def list_by_assessment(self, tenant_id: TenantId, assessment_id: str) -> list[Report]:
        query = (
            select(ReportModel)
            .where(
                ReportModel.tenant_id == tenant_id.value,
                ReportModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(ReportModel.version)
        )
        result = await self._session.execute(query)
        return [mappers.report_to_domain(m) for m in result.scalars().all()]

    async def list_latest_by_tenant(self, tenant_id: TenantId) -> list[Report]:
        latest_versions = (
            select(
                ReportModel.assessment_id.label("assessment_id"),
                func.max(ReportModel.version).label("max_version"),
            )
            .where(ReportModel.tenant_id == tenant_id.value)
            .group_by(ReportModel.assessment_id)
            .subquery()
        )
        query = select(ReportModel).join(
            latest_versions,
            and_(
                ReportModel.assessment_id == latest_versions.c.assessment_id,
                ReportModel.version == latest_versions.c.max_version,
            ),
        )
        result = await self._session.execute(query)
        return [mappers.report_to_domain(m) for m in result.scalars().all()]

    async def next_version(self, tenant_id: TenantId, assessment_id: str) -> int:
        query = select(func.coalesce(func.max(ReportModel.version), 0) + 1).where(
            ReportModel.tenant_id == tenant_id.value,
            ReportModel.assessment_id == uuid_module.UUID(assessment_id),
        )
        result = await self._session.scalar(query)
        assert result is not None  # coalesce(..., 0) + 1 always yields a value
        return result

    async def save(self, report: Report) -> None:
        model = await self._session.get(ReportModel, report.id.value)
        if model is None:
            model = ReportModel()
            mappers.apply_report_to_model(report, model)
            self._session.add(model)
            return
        mappers.apply_report_to_model(report, model)
