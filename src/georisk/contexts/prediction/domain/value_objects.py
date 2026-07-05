"""Value objects for the Prediction context's Sprint 8 scope:
correlation analysis and Multiple Linear Regression over a tenant's
``VariableSelection`` (Data Acquisition) and ``SamplingCampaign``
(Geospatial). This is a narrower, concrete resolution of the Domain
Model's originally-envisioned ``TrainedModel``/``Prediction`` pair (full
ML model registry — Random Forest/XGBoost/ANN/LSTM), which
``GEORISK_SCOPE_AND_FORMULA_DECISION_LOG.md`` flagged as needing "product
clarification" — Sprint 8's brief resolves that ambiguity explicitly:
statistical analysis (correlation + MLR) now, full ML model registry
deferred (out of scope: Random Forest, XGBoost, ANN, LSTM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class PredictionRunId(TypedId):
    pass


class PredictionMethod(StrEnum):
    PEARSON_CORRELATION = "PEARSON_CORRELATION"
    SPEARMAN_CORRELATION = "SPEARMAN_CORRELATION"
    KENDALL_CORRELATION = "KENDALL_CORRELATION"
    MULTIPLE_LINEAR_REGRESSION = "MULTIPLE_LINEAR_REGRESSION"


CORRELATION_METHODS: frozenset[PredictionMethod] = frozenset(
    {
        PredictionMethod.PEARSON_CORRELATION,
        PredictionMethod.SPEARMAN_CORRELATION,
        PredictionMethod.KENDALL_CORRELATION,
    }
)


class PredictionRunStatus(StrEnum):
    """Deliberately just two states, the same "no async job in between
    asked-to-run and done" reasoning ``ValidationRunStatus`` and
    ``StageResultStatus`` already established — correlation/MLR here are
    synchronous, pure-Python math (``correlation.py``/``regression.py``).
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Requirement #5 — Model Metadata Tracking. ``formula_version``
    mirrors the exact traceability discipline the Analysis Engine
    established in Sprint 5.2 (``StageResult.formula_version``): which
    exact formula generation produced this result, so a later formula
    correction doesn't silently reinterpret old runs.
    """

    model_type: PredictionMethod
    formula_version: str
    predictor_variable_codes: tuple[str, ...]
    dependent_variable_code: str | None
    sample_size: int
    computed_at: datetime

    def __post_init__(self) -> None:
        if not self.predictor_variable_codes:
            raise ValueError("ModelMetadata.predictor_variable_codes must not be empty")
        if self.sample_size < 1:
            raise ValueError("ModelMetadata.sample_size must be >= 1")


@dataclass(frozen=True, slots=True)
class CorrelationPair:
    variable_a: str
    variable_b: str
    coefficient: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    """Requirement #2 / #6 — Correlation Analysis Engine's result,
    stored as every pairwise coefficient among the selected variables
    (dependent included) — "Do not hardcode predictor variables" means
    this is however many pairs the selection produces, not a fixed
    matrix shape.
    """

    pairs: tuple[CorrelationPair, ...] = field(default_factory=tuple)

    def get(self, variable_a: str, variable_b: str) -> float | None:
        for pair in self.pairs:
            if {pair.variable_a, pair.variable_b} == {variable_a, variable_b}:
                return pair.coefficient
        return None


@dataclass(frozen=True, slots=True)
class RegressionVariableResult:
    """One predictor's contribution to the fitted MLR model — coefficient
    is the required field (Sprint 8 "Store: coefficients..."); the rest
    are the same diagnostic statistics ``core/mlr.py`` already computes
    as a byproduct of the same matrix algebra, kept as bonus detail."""

    code: str
    coefficient: float
    standardized_coefficient: float
    standard_error: float
    t_statistic: float
    p_value: float


@dataclass(frozen=True, slots=True)
class RegressionResult:
    """Requirement #3 / #6 — Multiple Linear Regression Engine's result.
    ``intercept``, each variable's ``coefficient``, ``r_squared``,
    ``adjusted_r_squared``, ``rmse``, and ``mae`` are exactly Sprint 8's
    required "Store:" list; ``f_statistic``/``mse``/``variables[*]``'s
    diagnostic fields are bonus detail ``core/mlr.py``'s ported algebra
    produces for free.
    """

    intercept: float
    variables: tuple[RegressionVariableResult, ...]
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    mae: float
    f_statistic: float
    mse: float

    def coefficient(self, code: str) -> float | None:
        for variable in self.variables:
            if variable.code == code:
                return variable.coefficient
        return None
