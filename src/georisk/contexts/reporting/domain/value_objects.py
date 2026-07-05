"""Value objects for the Reporting context (Domain Model §1 row 15:
``Report``'s ``ReportSnapshot``). Reporting is a **Conformist downstream
reader** (Domain Model §7): "Reporting reads published summaries/snapshots
from each upstream context and conforms entirely to their shapes; it never
requests a change to an upstream contract to suit a report layout —
report-specific transformation happens entirely inside Reporting." Every
section VO below is therefore Reporting's OWN shape, built from data handed
across the composition-root boundary (``application/ports.py``'s reader
Protocols) — never an import of another context's domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class ReportId(TypedId):
    pass


class ReportStatus(StrEnum):
    """"Historical snapshots" + "Immutable finalized reports" (Sprint 9)
    map onto Domain Model §1 row 15's own invariant: "Once FINALIZED,
    ReportSnapshot is immutable." ``DRAFT`` is the working copy a
    ``GenerateReport`` call produces (Application Layer §3's
    ``ReportSnapshotBuilder`` freezes the section data at THIS point, not
    at finalization); ``FinalizeReport`` (Application Layer §3) is the one
    remaining legal transition out of ``DRAFT``, and no method on
    ``Report`` can change a ``FINALIZED`` (or ``FAILED``) row further —
    "immutable" is therefore structural (no mutating method exists), not
    just a documented convention.
    """

    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class AssessmentSummary:
    """"Assessment Summary Reports" (requirement #3). Sourced from
    Assessment (Open Host Service — Domain Model §7) plus, for convenience,
    Geospatial's AOI/SamplingCampaign (both already assessment-scoped
    evidence in this platform's read APIs).
    """

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


@dataclass(frozen=True, slots=True)
class StageSummary:
    """One ``StageResult``'s frozen contribution to a ``RiskSummarySection``
    — every indicator the calculator produced, captured generically rather
    than picking out one hazard-specific "primary" code (e.g.
    ``flood_risk_index`` vs. ``wildfire_risk_index``), so this VO stays
    correct for both FIRAS and WRRAS (and any future hazard strategy)
    without Reporting ever hardcoding a strategy's indicator vocabulary.
    """

    stage_type: str
    status: str
    confidence_tier: str | None
    indicators: dict[str, float]
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class RiskSummarySection:
    """"FIRAS Reports" / "WRRAS Reports" (requirements #4/#5) — deliberately
    one shared shape for both, not two hazard-specific VOs: the underlying
    ``StageResult`` data is already hazard-agnostic (Analysis Engine's own
    design), so a hazard-specific ``FirasRiskSummary``/``WrrasRiskSummary``
    pair here would just be two names for the same fields.
    """

    hazard_type: str
    stages: tuple[StageSummary, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class StageFormulaVersion:
    """"Store: formula_versions" (Sprint 9) — one entry per included
    ``StageResult``, kept as its own top-level ``Report`` field (not only
    nested inside ``RiskSummarySection``) so a formula/strategy audit query
    never has to traverse the full risk summary to answer "what formula
    version computed this report."
    """

    stage_type: str
    formula_version: str | None


@dataclass(frozen=True, slots=True)
class CorrelationPairSummary:
    variable_a: str
    variable_b: str
    coefficient: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class RegressionSummary:
    intercept: float
    coefficients: dict[str, float]
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    mae: float


@dataclass(frozen=True, slots=True)
class PredictionSummary:
    """"Prediction Reports" / "Predictor summaries" (requirement #6) —
    one entry per ``PredictionRun`` included (the latest COMPLETED run per
    method), carrying that run's ``ModelMetadata`` ("Store:
    prediction_metadata") plus its outcome (correlation pairs XOR a
    regression fit, mirroring ``PredictionRun`` itself never populating
    both at once).
    """

    prediction_run_id: str
    method: str
    formula_version: str
    sample_size: int
    predictor_variable_codes: tuple[str, ...]
    dependent_variable_code: str | None
    correlation_pairs: tuple[CorrelationPairSummary, ...] = field(default_factory=tuple)
    regression: RegressionSummary | None = None


@dataclass(frozen=True, slots=True)
class DatasetProvenanceEntrySummary:
    """"Dataset provenance sections" (Sprint 9 Support list) / "Store:
    dataset_metadata". One entry per current (non-superseded) ``Dataset``
    visible to the tenant — Data Acquisition's ``Dataset`` is a tenant-wide
    catalog entry, not assessment-scoped (Sprint 7), so a Metadata Report
    surfaces the tenant's whole current catalog rather than a per-
    assessment subset that doesn't structurally exist yet.
    """

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


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    """"Validation summaries" (Sprint 9 Support list) — the latest
    ``ValidationRun`` for this assessment, if any. Sprint 10 extends this
    SAME VO (not a new ``Report``-level field — the constraint is "do not
    modify the Reporting Aggregate," and ``Report.validation_summary``'s
    type stays exactly ``ValidationSummary | None``) with a ``mode`` tag
    plus the regression metric fields, additive and defaulted so every
    pre-Sprint-10 classification-mode summary still round-trips unchanged.
    """

    validation_run_id: str
    subject_type: str
    verdict: str | None
    sample_size: int
    computed_at: datetime
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
