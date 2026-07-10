"""``RunPredictionCommand`` handler — one transaction, one aggregate
(``PredictionRun``), per Application Layer §9. Gathers the confirmed
``VariableSelection`` and the ``SamplingCampaign``'s sample count via the
injected reader ports, synthesizes observations via the injected
``PredictionDataProvider``, dispatches to the Correlation Analysis Engine
or the Multiple Linear Regression Engine depending on ``method``,
persists, and appends both resulting events to the outbox. Never imports
anything from ``contexts.geospatial`` or ``contexts.data_acquisition`` —
the "Do not modify" instruction's structural counterpart for Prediction,
identical reasoning to every prior context's handler.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.application.commands import RunPredictionCommand
from georisk.contexts.prediction.application.ports import (
    PredictionDataProvider,
    PredictorVariableInfo,
    SamplingCampaignReader,
    VariableSelectionReader,
)
from georisk.contexts.prediction.domain.correlation import compute_correlation_pairs
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.errors import (
    MissingDependentVariableError,
    SamplingCampaignNotAvailableError,
    VariableSelectionNotAvailableError,
)
from georisk.contexts.prediction.domain.events import (
    PredictionRunCompleted,
    PredictionRunFailed,
)
from georisk.contexts.prediction.domain.regression import compute_multiple_linear_regression
from georisk.contexts.prediction.domain.value_objects import (
    CORRELATION_METHODS,
    CorrelationPair,
    CorrelationResult,
    ModelMetadata,
    PredictionMethod,
    RegressionResult,
    RegressionVariableResult,
)
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)
from georisk.db.outbox_writer import append_event

_FORMULA_VERSIONS: dict[PredictionMethod, str] = {
    PredictionMethod.PEARSON_CORRELATION: "pearson-v1",
    PredictionMethod.SPEARMAN_CORRELATION: "spearman-v1",
    PredictionMethod.KENDALL_CORRELATION: "kendall-tau-b-v1",
    PredictionMethod.MULTIPLE_LINEAR_REGRESSION: "mlr-ols-v1",
}


def _deterministic_seed(*parts: str) -> int:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()
    return int(digest[:8], 16)


class RunPredictionHandler:
    def __init__(
        self,
        session: AsyncSession,
        variable_selection_reader: VariableSelectionReader,
        sampling_campaign_reader: SamplingCampaignReader,
        data_provider: PredictionDataProvider,
    ) -> None:
        self._session = session
        self._variable_selection_reader = variable_selection_reader
        self._sampling_campaign_reader = sampling_campaign_reader
        self._data_provider = data_provider
        self._repo = SqlAlchemyPredictionRunRepository(session)

    async def handle(self, command: RunPredictionCommand) -> PredictionRun:
        tenant_id = TenantId.from_string(command.tenant_id)
        method = PredictionMethod(command.method)
        event: PredictionRunCompleted | PredictionRunFailed

        try:
            selection = await self._variable_selection_reader.get_selection(
                tenant_id=command.tenant_id,
                variable_selection_id=command.variable_selection_id,
            )
            if selection is None:
                raise VariableSelectionNotAvailableError(
                    f"VariableSelection {command.variable_selection_id} not found"
                )
            if selection.status != "CONFIRMED":
                raise VariableSelectionNotAvailableError(
                    f"VariableSelection {command.variable_selection_id} is not CONFIRMED "
                    "— Variables must be selected from a confirmed VariableSelection"
                )

            sample_count = await self._sampling_campaign_reader.get_sample_count(
                tenant_id=command.tenant_id,
                sampling_campaign_id=command.sampling_campaign_id,
            )
            if sample_count is None:
                raise SamplingCampaignNotAvailableError(
                    f"SamplingCampaign {command.sampling_campaign_id} has no generated "
                    "sample points"
                )

            seed = _deterministic_seed(
                command.variable_selection_id, command.sampling_campaign_id, method.value
            )
            rows = await self._data_provider.generate_observations(
                tenant_id=command.tenant_id,
                hazard_type=selection.hazard_type,
                variables=selection.variables,
                sample_count=sample_count,
                seed=seed,
            )

            if method in CORRELATION_METHODS:
                model_metadata, correlation_result = _run_correlation(
                    method=method, variables=selection.variables, rows=rows
                )
                version = await self._repo.next_version(
                    tenant_id,
                    command.assessment_id,
                    command.variable_selection_id,
                    method,
                )
                result, event = PredictionRun.complete_correlation(
                    tenant_id=tenant_id,
                    assessment_id=command.assessment_id,
                    variable_selection_id=command.variable_selection_id,
                    sampling_campaign_id=command.sampling_campaign_id,
                    method=method,
                    version=version,
                    result=correlation_result,
                    model_metadata=model_metadata,
                    issued_by=command.issued_by,
                )
            else:
                model_metadata, regression_result = _run_regression(
                    variables=selection.variables, rows=rows
                )
                version = await self._repo.next_version(
                    tenant_id,
                    command.assessment_id,
                    command.variable_selection_id,
                    method,
                )
                result, event = PredictionRun.complete_regression(
                    tenant_id=tenant_id,
                    assessment_id=command.assessment_id,
                    variable_selection_id=command.variable_selection_id,
                    sampling_campaign_id=command.sampling_campaign_id,
                    version=version,
                    result=regression_result,
                    model_metadata=model_metadata,
                    issued_by=command.issued_by,
                )
        except Exception as exc:  # noqa: BLE001 — quarantining a resolution
            # or computation failure (missing/unconfirmed selection, no
            # generated sample points, a singular/collinear design matrix)
            # into a domain fact (PredictionRun.FAILED), the same "isolate
            # an untrusted boundary" reasoning as every prior handler.
            version = await self._repo.next_version(
                tenant_id, command.assessment_id, command.variable_selection_id, method
            )
            result, event = PredictionRun.failed(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                variable_selection_id=command.variable_selection_id,
                sampling_campaign_id=command.sampling_campaign_id,
                method=method,
                version=version,
                error=str(exc),
                issued_by=command.issued_by,
            )

        await self._repo.save(result)
        await append_event(
            self._session,
            aggregate_type="PredictionRun",
            aggregate_id=str(result.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return result


def _run_correlation(
    *,
    method: PredictionMethod,
    variables: tuple[PredictorVariableInfo, ...],
    rows: tuple[dict[str, float], ...],
) -> tuple[ModelMetadata, CorrelationResult]:
    data: dict[str, tuple[float, ...]] = {
        variable.code: tuple(row[variable.code] for row in rows) for variable in variables
    }
    raw_pairs = compute_correlation_pairs(data, method.value)
    pairs = tuple(
        CorrelationPair(variable_a=a, variable_b=b, coefficient=coefficient, sample_size=n)
        for a, b, coefficient, n in raw_pairs
    )
    metadata = ModelMetadata(
        model_type=method,
        formula_version=_FORMULA_VERSIONS[method],
        predictor_variable_codes=tuple(sorted(data.keys())),
        dependent_variable_code=None,
        sample_size=len(rows),
        computed_at=datetime.now(UTC),
    )
    return metadata, CorrelationResult(pairs=pairs)


def _run_regression(
    *, variables: tuple[PredictorVariableInfo, ...], rows: tuple[dict[str, float], ...]
) -> tuple[ModelMetadata, RegressionResult]:
    dependent_variables = [v for v in variables if v.variable_role == "DEPENDENT"]
    if len(dependent_variables) != 1:
        raise MissingDependentVariableError(
            "Multiple Linear Regression requires exactly one DEPENDENT variable in the "
            f"VariableSelection, found {len(dependent_variables)}"
        )
    dependent = dependent_variables[0]
    predictors = [v for v in variables if v.variable_role != "DEPENDENT"]
    if not predictors:
        raise MissingDependentVariableError(
            "Multiple Linear Regression requires at least one non-DEPENDENT predictor variable"
        )

    feature_names = [v.code for v in predictors]
    feature_matrix = [[row[code] for code in feature_names] for row in rows]
    y_values = [row[dependent.code] for row in rows]

    fit = compute_multiple_linear_regression(feature_matrix, y_values, feature_names)

    variable_results = tuple(
        RegressionVariableResult(
            code=feature_names[i],
            coefficient=fit.coefficients[i],
            standardized_coefficient=fit.standardized_coefficients[i],
            standard_error=fit.standard_errors[i],
            t_statistic=fit.t_statistics[i],
            p_value=fit.p_values[i],
        )
        for i in range(len(feature_names))
    )
    regression_result = RegressionResult(
        intercept=fit.intercept,
        variables=variable_results,
        r_squared=fit.r2,
        adjusted_r_squared=fit.adjusted_r2,
        rmse=fit.rmse,
        mae=fit.mae,
        f_statistic=fit.f_statistic,
        mse=fit.mse,
    )
    metadata = ModelMetadata(
        model_type=PredictionMethod.MULTIPLE_LINEAR_REGRESSION,
        formula_version=_FORMULA_VERSIONS[PredictionMethod.MULTIPLE_LINEAR_REGRESSION],
        predictor_variable_codes=tuple(feature_names),
        dependent_variable_code=dependent.code,
        sample_size=len(rows),
        computed_at=datetime.now(UTC),
    )
    return metadata, regression_result
