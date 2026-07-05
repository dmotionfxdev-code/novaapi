"""Composition-root glue wiring Prediction's real ``PredictionRun`` into
Validation's ``RegressionValidationSubjectResolver`` port
(``contexts/validation/application/ports.py``). Lives here, under
``api/``, deliberately outside both ``contexts.validation`` and
``contexts.prediction`` — the import-linter's peer-independence contract
forbids either from importing the other, so the only place code needing
both contexts' repositories can legally live is a neutral composition
layer, the identical role ``api/prediction_ports.py``/``api/
reporting_ports.py`` already play.

Unlike classification (whose real ``StageResult``/``Prediction`` ground
truth still has no resolver anywhere in this codebase — Sprint 4's stub
remains what's wired), this IS the real integration Sprint 10 asks for:
no raw per-observation dataset exists anywhere in this platform for a
``PredictionRun`` (Sprint 8's MLR engine never persisted the observations
it fit against, only the fit statistics), so the only honest thing this
resolver can do is adopt Prediction's own already-computed, already-
verified-correct RMSE/MAE/MSE/R²/Adjusted R² directly — not fabricate a
synthetic (y_true, y_pred) pair set dressed up as ground truth. Validation
still gets a genuinely useful job here: wrapping those numbers into a
formal, audited, threshold-gated ``ValidationRun`` record — governance
over a model's self-reported fit, not a second reimplementation of the
same arithmetic against data that doesn't exist.
"""

from __future__ import annotations

from georisk.contexts.prediction.domain.value_objects import PredictionRunId, PredictionRunStatus
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)
from georisk.contexts.validation.application.ports import RegressionValidationSubject
from georisk.contexts.validation.domain.value_objects import (
    RegressionMetricSet,
    RegressionModelMetadata,
)
from georisk.db.session import Database


class CompositionRootRegressionValidationSubjectResolver:
    """Implements Validation's ``RegressionValidationSubjectResolver`` port
    using Prediction's real repository directly."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def resolve(
        self, *, subject_id: str, assessment_id: str, tenant_id: str
    ) -> RegressionValidationSubject:
        async with self._db.session() as session:
            repo = SqlAlchemyPredictionRunRepository(session)
            run = await repo.get_by_id(PredictionRunId.from_string(subject_id))
            if run is None or str(run.tenant_id) != tenant_id:
                raise ValueError(f"PredictionRun {subject_id} not found")
            if run.status is not PredictionRunStatus.COMPLETED:
                raise ValueError(f"PredictionRun {subject_id} did not complete successfully")
            if run.regression_result is None or run.model_metadata is None:
                raise ValueError(
                    f"PredictionRun {subject_id} has no regression fit to validate "
                    "(not a Multiple Linear Regression run)"
                )
            if run.assessment_id != assessment_id:
                raise ValueError(
                    f"PredictionRun {subject_id} does not belong to assessment {assessment_id}"
                )

            regression = run.regression_result
            metadata = run.model_metadata
            metrics = RegressionMetricSet(
                sample_size=metadata.sample_size,
                rmse=regression.rmse,
                mae=regression.mae,
                mse=regression.mse,
                r_squared=regression.r_squared,
                adjusted_r_squared=regression.adjusted_r_squared,
            )
            model_metadata = RegressionModelMetadata(
                prediction_run_id=str(run.id),
                method=run.method.value,
                formula_version=metadata.formula_version,
                predictor_variable_codes=metadata.predictor_variable_codes,
                dependent_variable_code=metadata.dependent_variable_code,
                sample_size=metadata.sample_size,
                computed_at=metadata.computed_at,
            )
            return RegressionValidationSubject(metrics=metrics, model_metadata=model_metadata)
