"""The ``PredictionRun`` aggregate (Sprint 8 requirement #1) — the
Prediction context's sole aggregate root for this sprint's scope.
Write-once-per-version, the same immutability discipline
``StageResult``/``AreaOfInterest``/``Dataset`` already established
(requirement #7 — Versioning): re-running the same
``(assessment, variable_selection, method)`` combination creates a new
row, never mutates an existing one in place.

Nothing here imports from ``contexts.geospatial`` or
``contexts.data_acquisition`` — structurally enforced by the
import-linter's peer-independence contract. ``variable_selection_id``/
``sampling_campaign_id`` are soft, plain-string cross-context references,
the same pattern every prior context's aggregates use for a peer
context's identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.events import PredictionRunCompleted, PredictionRunFailed
from georisk.contexts.prediction.domain.value_objects import (
    CorrelationResult,
    ModelMetadata,
    PredictionMethod,
    PredictionRunId,
    PredictionRunStatus,
    RegressionResult,
)


@dataclass(slots=True)
class PredictionRun:
    id: PredictionRunId
    tenant_id: TenantId
    assessment_id: str
    variable_selection_id: str
    sampling_campaign_id: str
    method: PredictionMethod
    version: int
    status: PredictionRunStatus
    model_metadata: ModelMetadata | None
    correlation_result: CorrelationResult | None
    regression_result: RegressionResult | None
    error: str | None
    issued_by: str
    created_at: datetime

    @classmethod
    def complete_correlation(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        variable_selection_id: str,
        sampling_campaign_id: str,
        method: PredictionMethod,
        version: int,
        result: CorrelationResult,
        model_metadata: ModelMetadata,
        issued_by: str,
    ) -> tuple[PredictionRun, PredictionRunCompleted]:
        run = cls(
            id=PredictionRunId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            variable_selection_id=variable_selection_id,
            sampling_campaign_id=sampling_campaign_id,
            method=method,
            version=version,
            status=PredictionRunStatus.COMPLETED,
            model_metadata=model_metadata,
            correlation_result=result,
            regression_result=None,
            error=None,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
        )
        event = PredictionRunCompleted(
            prediction_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            method=method.value,
            version=version,
            formula_version=model_metadata.formula_version,
            sample_size=model_metadata.sample_size,
        )
        return run, event

    @classmethod
    def complete_regression(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        variable_selection_id: str,
        sampling_campaign_id: str,
        version: int,
        result: RegressionResult,
        model_metadata: ModelMetadata,
        issued_by: str,
    ) -> tuple[PredictionRun, PredictionRunCompleted]:
        run = cls(
            id=PredictionRunId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            variable_selection_id=variable_selection_id,
            sampling_campaign_id=sampling_campaign_id,
            method=PredictionMethod.MULTIPLE_LINEAR_REGRESSION,
            version=version,
            status=PredictionRunStatus.COMPLETED,
            model_metadata=model_metadata,
            correlation_result=None,
            regression_result=result,
            error=None,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
        )
        event = PredictionRunCompleted(
            prediction_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            method=PredictionMethod.MULTIPLE_LINEAR_REGRESSION.value,
            version=version,
            formula_version=model_metadata.formula_version,
            sample_size=model_metadata.sample_size,
        )
        return run, event

    @classmethod
    def failed(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        variable_selection_id: str,
        sampling_campaign_id: str,
        method: PredictionMethod,
        version: int,
        error: str,
        issued_by: str,
    ) -> tuple[PredictionRun, PredictionRunFailed]:
        run = cls(
            id=PredictionRunId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            variable_selection_id=variable_selection_id,
            sampling_campaign_id=sampling_campaign_id,
            method=method,
            version=version,
            status=PredictionRunStatus.FAILED,
            model_metadata=None,
            correlation_result=None,
            regression_result=None,
            error=error,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
        )
        event = PredictionRunFailed(
            prediction_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            method=method.value,
            version=version,
            error=error,
        )
        return run, event
