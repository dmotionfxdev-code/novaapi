"""Value objects for the Validation context (Domain Model §1 row 14: the
`ValidationRun` aggregate's `MetricSet`, `ConfusionMatrix`, `Verdict`).

Validation is a Generic Subdomain (Domain Model §4): "a validation run
judges predicted-vs-observed with standard statistics — it has no opinion
about floods, only about numbers." Nothing in this module (or anywhere in
this context) references a hazard type, an assessment's internal fields, or
a GIS concept. `subject_id` is a soft, plain-string cross-context reference
(the thing being judged — a `StageResultId` or `PredictionId` in the full
design, neither of which context exists yet) rather than a typed id
imported from another context, exactly matching the pattern
`Assessment.workflow_template_id: str` already established in Sprint 3 —
required here structurally, since the import-linter's peer-independence
contract forbids `validation` from importing `assessment`/`analysis`/
`prediction` at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class ValidationRunId(TypedId):
    pass


class SubjectType(StrEnum):
    """What's being judged. Only two subject kinds exist in the full
    design (Domain Model §1 row 14) — neither the Analysis Engine's
    `StageResult` nor the Prediction context exist yet this sprint, so
    both values are honest placeholders a real subject will resolve
    against once those contexts land (Roadmap Sprint 5/6 equivalents).
    """

    STAGE_RESULT = "STAGE_RESULT"
    PREDICTION = "PREDICTION"


class ValidationMode(StrEnum):
    """Sprint 10: "Support: ValidationMode.CLASSIFICATION,
    ValidationMode.REGRESSION" — every ``ValidationRun`` is tagged with
    exactly one mode, determining whether it carries a classification
    ``MetricSet`` (confusion matrix, accuracy, F1, ROC/AUC) or a regression
    ``RegressionMetricSet`` (RMSE/MAE/MSE/R²/Adjusted R²), never both.
    Every run that predates this field is unambiguously ``CLASSIFICATION``
    — no other mode existed before Sprint 10 (see the migration's
    ``server_default``), so backfilling it is a known fact, not a guess.
    """

    CLASSIFICATION = "CLASSIFICATION"
    REGRESSION = "REGRESSION"


class ValidationRunStatus(StrEnum):
    """Deliberately just two states, not a PENDING/RUNNING/COMPLETED/FAILED
    pipeline: metric computation here is synchronous, pure-Python math
    (`metrics.py`, ported near-verbatim from `core/validation.py`) with no
    async job in between — there is no observable moment between "asked to
    run" and "done" for this sprint's implementation to model. A real
    async resolution pipeline (Roadmap Sprint 9's full ground-truth data
    acquisition) would be the point to add intermediate states; adding
    them now with no behavior to attach would be speculative.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ValidationThresholds:
    """The "declared thresholds" Domain Model §1 row 14 says `Verdict` is a
    pure function against. Every field is optional — an unset threshold is
    simply not checked (see `metrics.compute_verdict`); a run with no
    thresholds declared at all always passes.

    Sprint 10 adds the regression-mode counterparts (``max_rmse``/
    ``max_mae``/``min_r_squared``/``min_adjusted_r_squared``) as additional
    optional fields on this SAME value object rather than a parallel
    ``RegressionValidationThresholds`` type — it's already just a bag of
    independently-optional threshold fields, and a single ``ValidationRun``
    only ever checks the subset relevant to its own ``mode`` (see
    `metrics.compute_verdict`/`regression_metrics.compute_regression_verdict`).
    """

    min_overall_accuracy: float | None = None
    min_precision: float | None = None
    min_recall: float | None = None
    min_f1_score: float | None = None
    min_auc: float | None = None
    max_rmse: float | None = None
    max_mae: float | None = None
    min_r_squared: float | None = None
    min_adjusted_r_squared: float | None = None


@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    """N-class confusion matrix — `matrix[i][j]` is the count of samples
    whose actual label is `labels[i]` and predicted label is `labels[j]`.
    The binary case (the shape most FIRAS/WRRAS validations actually use)
    is exactly `labels = (negative, positive)`, 2x2.
    """

    labels: tuple[str, ...]
    matrix: tuple[tuple[int, ...], ...]

    def total(self) -> int:
        return sum(sum(row) for row in self.matrix)

    def correct(self) -> int:
        return sum(self.matrix[i][i] for i in range(len(self.labels)))

    def per_class_counts(self, label: str) -> tuple[int, int, int, int]:
        """One-vs-rest ``(tp, fp, tn, fn)`` for a single label — the same
        decomposition every row of `core/validation.py`'s
        `build_confusion_matrix(...)['per_class']` used.
        """
        idx = self.labels.index(label)
        tp = self.matrix[idx][idx]
        fp = sum(self.matrix[i][idx] for i in range(len(self.labels))) - tp
        fn = sum(self.matrix[idx]) - tp
        tn = self.total() - tp - fp - fn
        return tp, fp, tn, fn

    def binary_counts(self) -> tuple[int, int, int, int] | None:
        """``(tp, fp, tn, fn)`` treating ``labels[1]`` as the positive
        class — only meaningful, and only returned, for exactly two
        labels.
        """
        if len(self.labels) != 2:
            return None
        return self.per_class_counts(self.labels[1])


@dataclass(frozen=True, slots=True)
class RocPoint:
    fpr: float
    tpr: float
    threshold: float


@dataclass(frozen=True, slots=True)
class MetricSet:
    """Domain Model §1 row 14's `MetricSet` (VO) — requirements #2-9 of the
    Sprint 4 brief (Validation Metrics, Confusion Matrix, Accuracy,
    Precision, Recall, F1 Score, ROC, AUC) all land as fields here.
    `precision`/`recall`/`f1_score` are the binary-positive-class values
    when the confusion matrix is 2x2, and macro-averaged across classes
    otherwise (`metrics.compute_metric_set`'s docstring covers the exact
    rule) — `specificity` has no well-defined macro-average and is left
    unset (``None``) outside the binary case.
    """

    confusion_matrix: ConfusionMatrix
    sample_size: int
    overall_accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    specificity: float | None = None
    f1_score: float | None = None
    kappa: float | None = None
    auc: float | None = None
    optimal_threshold: float | None = None
    roc_points: tuple[RocPoint, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RegressionMetricSet:
    """Sprint 10 requirement #2 — the regression counterpart of
    `MetricSet`: RMSE, MAE, MSE, R², Adjusted R². Computed by
    `regression_metrics.compute_regression_metric_set` from a
    `RegressionValidationDataset`, exactly mirroring how `MetricSet` is
    computed by `metrics.compute_metric_set` from a `ValidationDataset`.
    """

    sample_size: int
    rmse: float
    mae: float
    mse: float
    r_squared: float
    adjusted_r_squared: float


@dataclass(frozen=True, slots=True)
class RegressionModelMetadata:
    """Sprint 10 requirement #6 ("Persist: ... model metadata") — the
    predictive model being judged, translated into Validation's own
    vocabulary at the composition-root boundary (never importing
    Prediction's own ``ModelMetadata`` domain type directly — the same
    "conformist downstream reader" discipline Reporting established in
    Sprint 9, applied here to Validation's read side of its relationship
    with Prediction).
    """

    prediction_run_id: str
    method: str
    formula_version: str
    predictor_variable_codes: tuple[str, ...]
    dependent_variable_code: str | None
    sample_size: int
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class RegressionValidationDataset:
    """What a `RegressionValidationSubjectResolver`
    (application/ports.py) hands back for
    `regression_metrics.compute_regression_metric_set` to turn into a
    `RegressionMetricSet` — the regression-mode counterpart of
    `ValidationDataset`. ``num_predictors`` is required (unlike
    classification, Adjusted R² cannot be computed from ``y_true``/
    ``y_pred`` alone).
    """

    y_true: tuple[float, ...]
    y_pred: tuple[float, ...]
    num_predictors: int

    def __post_init__(self) -> None:
        if len(self.y_true) < 2:
            raise ValueError("RegressionValidationDataset needs at least 2 samples")
        if len(self.y_true) != len(self.y_pred):
            raise ValueError("y_true and y_pred must have the same length")
        if self.num_predictors < 1:
            raise ValueError("num_predictors must be at least 1")


@dataclass(frozen=True, slots=True)
class ValidationDataset:
    """What a `ValidationSubjectResolver` (application/ports.py) hands
    back for `metrics.compute_metric_set` to turn into a `MetricSet` —
    Domain Model §7's "both sides submit (predicted, observed) value
    pairs to Validation" made concrete. ``y_scores``, when present, enables
    the ROC/AUC computation (requirements #8/#9); its positive class is
    always the lexicographically-last entry of the resolved label set
    (documented in `metrics.compute_metric_set`).
    """

    y_true: tuple[str, ...]
    y_pred: tuple[str, ...]
    y_scores: tuple[float, ...] | None = None
    labels: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.y_true:
            raise ValueError("ValidationDataset must contain at least one sample")
        if len(self.y_true) != len(self.y_pred):
            raise ValueError("y_true and y_pred must have the same length")
        if self.y_scores is not None and len(self.y_scores) != len(self.y_true):
            raise ValueError("y_scores must have the same length as y_true")
