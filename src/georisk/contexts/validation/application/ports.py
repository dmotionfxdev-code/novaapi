"""``ValidationSubjectResolver`` — the seam Domain Model §7 calls the "Open
Host Service" side of Validation's relationship with Analysis Engine/
Prediction: "both sides submit (predicted, observed) value pairs to
Validation." Concretely, given a ``subjectId``/``subjectType`` (what's
being judged) it produces the ``(predicted, observed)`` pairs
(``ValidationDataset``) `metrics.compute_metric_set` turns into a
``MetricSet``.

Neither of the real subject sources (Analysis Engine's ``StageResult``,
the Prediction context) exist yet — this sprint's brief explicitly asks for
Validation to "integrate with Workflow Engine as a stage" now, ahead of the
original roadmap's Sprint 5/6 sequencing. ``StubValidationSubjectResolver``
is this sprint's honest placeholder, matching the same pattern already used
for stage execution itself (`contexts.assessment.application.workflow_engine
.ImmediateSuccessStageExecutor`): it proves the resolution seam and the
metrics pipeline behind it are wired correctly, without pretending to have
real ground-truth data this platform doesn't have anywhere yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from georisk.contexts.validation.domain.regression_metrics import compute_regression_metric_set
from georisk.contexts.validation.domain.value_objects import (
    RegressionMetricSet,
    RegressionModelMetadata,
    RegressionValidationDataset,
    SubjectType,
    ValidationDataset,
)


class ValidationSubjectResolver(Protocol):
    async def resolve(
        self, *, subject_id: str, subject_type: SubjectType, assessment_id: str
    ) -> ValidationDataset: ...


@dataclass(frozen=True, slots=True)
class RegressionValidationSubject:
    """What a ``RegressionValidationSubjectResolver`` hands back — reuses
    Validation's own domain VOs directly (``RegressionMetricSet``/
    ``RegressionModelMetadata``) rather than a separate ports-level DTO,
    the same precedent ``ValidationSubjectResolver``/``ValidationDataset``
    already set in Sprint 4: these VOs are Validation's OWN vocabulary
    already, not a peer context's domain type needing translation at this
    boundary (that translation happens one layer further out, at the
    composition-root implementation reading Prediction's real data).
    """

    metrics: RegressionMetricSet
    model_metadata: RegressionModelMetadata | None


class RegressionValidationSubjectResolver(Protocol):
    async def resolve(
        self, *, subject_id: str, assessment_id: str, tenant_id: str
    ) -> RegressionValidationSubject: ...


class StubValidationSubjectResolver:
    """Returns a fixed, non-trivial dataset (accuracy ≈0.71, F1 ≈0.67 —
    just clears `metrics.DEFAULT_VALIDATION_THRESHOLDS`) regardless of the
    subject asked for. Deliberately not a perfect-score dataset: an
    always-PASS stub would make it impossible to tell, from the outside,
    whether the verdict machinery is actually being exercised or just
    trivially satisfied. Replacing this with a resolver backed by real
    ``StageResult``/``Prediction`` ground truth is Roadmap Sprint 5/6's
    job, once those contexts exist.
    """

    async def resolve(
        self, *, subject_id: str, subject_type: SubjectType, assessment_id: str
    ) -> ValidationDataset:
        return ValidationDataset(
            y_true=(
                "POSITIVE",
                "POSITIVE",
                "POSITIVE",
                "NEGATIVE",
                "NEGATIVE",
                "NEGATIVE",
                "NEGATIVE",
            ),
            y_pred=(
                "POSITIVE",
                "POSITIVE",
                "NEGATIVE",
                "NEGATIVE",
                "NEGATIVE",
                "NEGATIVE",
                "POSITIVE",
            ),
            y_scores=(0.92, 0.81, 0.55, 0.20, 0.15, 0.10, 0.60),
            labels=("NEGATIVE", "POSITIVE"),
        )


class StubRegressionValidationSubjectResolver:
    """Sprint 10's regression-mode counterpart of
    ``StubValidationSubjectResolver`` — a fixed, non-trivial (y_true,
    y_pred) pair set with real, deliberately-imperfect noise (not a
    perfect-fit stub, the same "prove the verdict machinery is actually
    exercised" reasoning), fed through the real
    ``compute_regression_metric_set`` to produce genuine metrics. Used for
    ad-hoc/handler-level testing; the composition-root
    ``CompositionRootRegressionValidationSubjectResolver`` (``api/
    validation_ports.py``) is what's actually wired into production,
    reading a real ``PredictionRun``'s already-computed regression fit —
    unlike classification, whose real ``StageResult``/``Prediction``
    ground truth still has no resolver at all (Sprint 4's stub remains
    what's wired), regression validation's very purpose this sprint is to
    have that real integration, so this stub is never the production
    default.
    """

    async def resolve(
        self, *, subject_id: str, assessment_id: str, tenant_id: str
    ) -> RegressionValidationSubject:
        dataset = RegressionValidationDataset(
            y_true=(10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 28.0, 16.0),
            y_pred=(12.5, 17.5, 17.0, 22.0, 27.5, 14.5, 15.5, 24.5, 25.0, 18.5),
            num_predictors=2,
        )
        metrics = compute_regression_metric_set(dataset)
        return RegressionValidationSubject(metrics=metrics, model_metadata=None)
