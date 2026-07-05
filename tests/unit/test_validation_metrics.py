"""Unit tests for the ported/reimplemented validation metrics kernel
(`contexts.validation.domain.metrics`) — pure computation, no I/O. Proves
the AUC reimplementation is exact against textbook reference values (not
just "looks reasonable"), and that confusion-matrix-derived metrics match
hand-computed expectations for both the binary and multi-class cases.
"""

from __future__ import annotations

import pytest

from georisk.contexts.validation.domain.metrics import (
    _compute_roc,
    build_confusion_matrix,
    compute_metric_set,
    compute_verdict,
)
from georisk.contexts.validation.domain.value_objects import (
    ValidationDataset,
    ValidationThresholds,
    Verdict,
)

pytestmark = pytest.mark.unit


# --- build_confusion_matrix -----------------------------------------------


def test_build_confusion_matrix_binary_counts() -> None:
    cm = build_confusion_matrix(
        y_true=["POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"],
        y_pred=["POSITIVE", "NEGATIVE", "NEGATIVE", "POSITIVE"],
        labels=["NEGATIVE", "POSITIVE"],
    )
    assert cm.labels == ("NEGATIVE", "POSITIVE")
    assert cm.total() == 4
    assert cm.correct() == 2
    tp, fp, tn, fn = cm.binary_counts()
    assert (tp, fp, tn, fn) == (1, 1, 1, 1)


def test_build_confusion_matrix_derives_labels_when_not_given() -> None:
    cm = build_confusion_matrix(y_true=["A", "B", "A"], y_pred=["A", "A", "A"])
    assert cm.labels == ("A", "B")


def test_confusion_matrix_perfect_agreement_has_full_diagonal() -> None:
    cm = build_confusion_matrix(
        y_true=["A", "B", "C"], y_pred=["A", "B", "C"], labels=["A", "B", "C"]
    )
    assert cm.correct() == cm.total() == 3


# --- compute_metric_set: binary -------------------------------------------


def test_compute_metric_set_binary_matches_hand_computed_values() -> None:
    dataset = ValidationDataset(
        y_true=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        y_pred=("POSITIVE", "NEGATIVE", "NEGATIVE", "POSITIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    metrics = compute_metric_set(dataset)
    assert metrics.sample_size == 4
    assert metrics.overall_accuracy == 0.5
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.specificity == 0.5
    assert metrics.f1_score == 0.5


def test_compute_metric_set_perfect_binary_classification() -> None:
    dataset = ValidationDataset(
        y_true=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        y_pred=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    metrics = compute_metric_set(dataset)
    assert metrics.overall_accuracy == 1.0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1_score == 1.0
    assert metrics.kappa == 1.0


# --- compute_metric_set: multi-class (macro-average) ----------------------


def test_compute_metric_set_multiclass_macro_averages() -> None:
    # 3-class, one misclassification (last A predicted as B).
    dataset = ValidationDataset(
        y_true=("A", "A", "B", "B", "C", "C"),
        y_pred=("A", "B", "B", "B", "C", "C"),
        labels=("A", "B", "C"),
    )
    metrics = compute_metric_set(dataset)
    assert metrics.specificity is None  # not defined for >2 classes
    assert metrics.overall_accuracy == pytest.approx(5 / 6)
    # A: tp=1,fp=0,fn=1 -> p=1.0,r=0.5,f1=2/3
    # B: tp=2,fp=1,fn=0 -> p=2/3,r=1.0,f1=0.8
    # C: tp=2,fp=0,fn=0 -> p=1.0,r=1.0,f1=1.0
    expected_precision = (1.0 + 2 / 3 + 1.0) / 3
    expected_recall = (0.5 + 1.0 + 1.0) / 3
    assert metrics.precision == pytest.approx(expected_precision, abs=1e-6)
    assert metrics.recall == pytest.approx(expected_recall, abs=1e-6)


# --- ROC / AUC --------------------------------------------------------------


def test_roc_auc_textbook_reference_value() -> None:
    """Classic 4-sample example with a known-correct AUC of 0.75, hand
    verified: positives=[0.35, 0.8], negatives=[0.1, 0.4]; rank_sum(pos) =
    2 + 4 = 6; AUC = (6 - 2*3/2) / (2*2) = 0.75.
    """
    auc, _threshold, _points = _compute_roc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
    assert auc == pytest.approx(0.75)


def test_roc_auc_perfect_separation_is_one() -> None:
    auc, _threshold, _points = _compute_roc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert auc == pytest.approx(1.0)


def test_roc_auc_all_tied_scores_is_half() -> None:
    auc, _threshold, _points = _compute_roc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5])
    assert auc == pytest.approx(0.5)


def test_roc_auc_degenerate_single_class_returns_default() -> None:
    auc, threshold, points = _compute_roc([1, 1, 1], [0.9, 0.8, 0.7])
    assert auc == 0.5
    assert threshold == 0.5
    assert points == ()


def test_compute_metric_set_includes_auc_when_scores_provided() -> None:
    dataset = ValidationDataset(
        y_true=("NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"),
        y_pred=("NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"),
        y_scores=(0.1, 0.4, 0.35, 0.8),
        labels=("NEGATIVE", "POSITIVE"),
    )
    metrics = compute_metric_set(dataset)
    assert metrics.auc == pytest.approx(0.75)
    assert metrics.roc_points  # non-empty


def test_compute_metric_set_omits_auc_without_scores() -> None:
    dataset = ValidationDataset(
        y_true=("POSITIVE", "NEGATIVE"),
        y_pred=("POSITIVE", "NEGATIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    metrics = compute_metric_set(dataset)
    assert metrics.auc is None
    assert metrics.roc_points == ()


# --- ValidationDataset validation -------------------------------------------


def test_validation_dataset_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        ValidationDataset(y_true=(), y_pred=())


def test_validation_dataset_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        ValidationDataset(y_true=("A", "B"), y_pred=("A",))


def test_validation_dataset_rejects_mismatched_scores_length() -> None:
    with pytest.raises(ValueError, match="y_scores"):
        ValidationDataset(y_true=("A", "B"), y_pred=("A", "B"), y_scores=(0.5,))


# --- compute_verdict ---------------------------------------------------------


def test_compute_verdict_passes_when_no_thresholds_declared() -> None:
    dataset = ValidationDataset(y_true=("A",), y_pred=("B",))
    metrics = compute_metric_set(dataset)
    assert compute_verdict(metrics, ValidationThresholds()) is Verdict.PASS


def test_compute_verdict_fails_when_a_declared_threshold_is_not_met() -> None:
    dataset = ValidationDataset(
        y_true=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        y_pred=("POSITIVE", "NEGATIVE", "NEGATIVE", "POSITIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    metrics = compute_metric_set(dataset)  # accuracy 0.5
    thresholds = ValidationThresholds(min_overall_accuracy=0.9)
    assert compute_verdict(metrics, thresholds) is Verdict.FAIL


def test_compute_verdict_fails_closed_when_metric_is_missing() -> None:
    dataset = ValidationDataset(
        y_true=("POSITIVE", "NEGATIVE"),
        y_pred=("POSITIVE", "NEGATIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    metrics = compute_metric_set(dataset)  # no y_scores -> auc is None
    thresholds = ValidationThresholds(min_auc=0.5)
    assert compute_verdict(metrics, thresholds) is Verdict.FAIL
