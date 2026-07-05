"""Ports Reporting needs from its upstream peers — Assessment (+
Geospatial's AOI/SamplingCampaign, folded into the same reader for
convenience), Analysis Engine's ``StageResult``, Prediction's
``PredictionRun``, Data Acquisition's ``Dataset`` catalog, and Validation's
``ValidationRun``. Reporting's own bounded context may not import any of
these peers directly (import-linter's independence contract), so these
Protocols are the seam: a composition-root module (``api/reporting_ports.py``,
outside every context involved — the same role ``api/workflow_stage_executors.py``
and ``api/prediction_ports.py`` already play) implements each reader by
calling that context's own repository directly, since composition roots are
exempt from the peer-independence contract by design.

Every reader returns ``None``/an empty list rather than raising when its
section's data simply doesn't exist yet (no ``PredictionRun`` has been run,
no ``ValidationRun`` exists) — those sections are optional/best-effort on a
``Report`` (Domain Model §7: "Reporting reads published summaries/snapshots
... it never requests a change to an upstream contract"). Only the
assessment itself not existing is a hard failure (``AssessmentReader``
returning ``None`` — the one case ``application/handlers.py`` treats as
fatal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AssessmentInfo:
    assessment_id: str
    name: str
    hazard_type: str
    status: str
    created_at: datetime
    aoi_name: str | None = None
    aoi_version: int | None = None
    aoi_area_m2: float | None = None
    sampling_campaign_name: str | None = None
    sample_count: int | None = None


class AssessmentReader(Protocol):
    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None: ...


@dataclass(frozen=True, slots=True)
class StageResultInfo:
    stage_type: str
    status: str
    confidence_tier: str | None
    formula_version: str | None
    strategy_version: str | None
    indicators: dict[str, float]
    computed_at: datetime


class StageResultReader(Protocol):
    async def list_latest_stage_results(
        self, *, tenant_id: str, assessment_id: str, hazard_type: str
    ) -> list[StageResultInfo]:
        """The latest COMPLETE result for each of the five core gating
        stages (HAZARD/EXPOSURE/VULNERABILITY/RISK/RESILIENCE) that
        currently have one — never the three optional, non-gating WRRAS
        supporting-analysis stages (FIRE_REGIME/BURN_OCCURRENCE_PROBABILITY/
        BURN_SEVERITY — Sprint 6's scope decision keeps those outside the
        main risk pipeline)."""
        ...


@dataclass(frozen=True, slots=True)
class RegressionInfo:
    intercept: float
    coefficients: dict[str, float]
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    mae: float


@dataclass(frozen=True, slots=True)
class PredictionRunInfo:
    prediction_run_id: str
    method: str
    formula_version: str
    sample_size: int
    predictor_variable_codes: tuple[str, ...]
    dependent_variable_code: str | None
    correlation_pairs: tuple[tuple[str, str, float, int], ...] = field(default_factory=tuple)
    regression: RegressionInfo | None = None


class PredictionReader(Protocol):
    async def list_latest_prediction_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[PredictionRunInfo]:
        """The latest COMPLETED ``PredictionRun`` per method (Pearson/
        Spearman/Kendall/MLR each tracked independently)."""
        ...


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    dataset_id: str
    name: str
    version: int
    dataset_type: str
    provider: str
    processing_method: str
    is_mlr_ready: bool
    is_correlation_ready: bool
    provenance_entry_count: int
    latest_provenance_action: str | None
    latest_provenance_at: datetime | None


class DatasetCatalogReader(Protocol):
    async def list_current_datasets(self, *, tenant_id: str) -> list[DatasetInfo]:
        """Every current (non-superseded) catalogued dataset visible to
        this tenant."""
        ...


@dataclass(frozen=True, slots=True)
class ValidationRunInfo:
    validation_run_id: str
    subject_type: str
    verdict: str | None
    sample_size: int
    computed_at: datetime
    # Sprint 10: "Integrate with Reporting Context" — ``mode`` tells the
    # report builder which of the two metric groups below is populated.
    # Classification fields are unchanged from Sprint 9; the regression
    # fields are additive, defaulted for every pre-Sprint-10 classification
    # run this DTO is ever built from.
    mode: str = "CLASSIFICATION"
    overall_accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1_score: float | None = None
    kappa: float | None = None
    auc: float | None = None
    rmse: float | None = None
    mae: float | None = None
    mse: float | None = None
    r_squared: float | None = None
    adjusted_r_squared: float | None = None


class ValidationReader(Protocol):
    async def get_latest_validation(
        self, *, tenant_id: str, assessment_id: str
    ) -> ValidationRunInfo | None: ...
