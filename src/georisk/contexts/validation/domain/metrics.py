"""Pure computation — no I/O, no ORM, no aggregate state. Ported from the
old system's `core/validation.py`, which the architecture review named
explicitly as "the one module... already correctly designed" (Architecture
Redesign §16) and instructed to "preserve... exactly." The classification-
metrics formulas (`_compute_classification_metrics`, `_compute_kappa`) and
`build_confusion_matrix` are a near-verbatim port; ROC/AUC is a genuine
reimplementation (`_compute_roc`) rather than a port, because the legacy
version depended on scikit-learn purely for arithmetic this platform's own
established policy defers heavy/ML dependencies until a sprint that needs
real modeling work introduces them (Sprint 0's dependency list; scikit-learn
lands with Prediction, Roadmap Sprint 6) — the rank-sum/Mann-Whitney-U AUC
formula used here is exact, not an approximation, and is verified against
the textbook reference example in `tests/unit/test_validation_metrics.py`.

Regression metrics (20 of them in the legacy module), spatial IoU/CSI
metrics, and uncertainty scoring are deliberately NOT ported — the Sprint 4
brief's numbered requirements are Confusion Matrix, Accuracy, Precision,
Recall, F1, ROC, AUC only; porting unrequested capability would be scope
creep this codebase's own standard explicitly rejects.
"""

from __future__ import annotations

from collections.abc import Sequence

from georisk.contexts.validation.domain.value_objects import (
    ConfusionMatrix,
    MetricSet,
    RocPoint,
    ValidationDataset,
    ValidationThresholds,
    Verdict,
)

# A reasonable, documented default gate — applied whenever a RunValidation
# command doesn't declare its own thresholds (the public API doesn't expose
# threshold overrides this sprint; Domain Model §1 row 14 only requires that
# *some* declared thresholds exist for the verdict to be a pure function
# against, not that every caller supplies its own). Loosely mirrors the
# legacy four-tier `get_validation_status`'s "acceptable" boundary, adapted
# to this platform's accuracy/F1-based MetricSet rather than kappa/r².
DEFAULT_VALIDATION_THRESHOLDS = ValidationThresholds(
    min_overall_accuracy=0.70,
    min_f1_score=0.60,
)


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_confusion_matrix(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] | None = None
) -> ConfusionMatrix:
    resolved_labels = tuple(labels) if labels else tuple(sorted(set(y_true) | set(y_pred)))
    index = {label: i for i, label in enumerate(resolved_labels)}
    n = len(resolved_labels)
    counts = [[0] * n for _ in range(n)]
    for actual, predicted in zip(y_true, y_pred, strict=False):
        i, j = index.get(actual), index.get(predicted)
        if i is not None and j is not None:
            counts[i][j] += 1
    return ConfusionMatrix(labels=resolved_labels, matrix=tuple(tuple(row) for row in counts))


def _compute_kappa(cm: ConfusionMatrix) -> float:
    """Cohen's Kappa — ported directly from `build_confusion_matrix`'s
    kappa computation in `core/validation.py`."""
    total = cm.total()
    if total == 0:
        return 0.0
    n = len(cm.labels)
    row_sums = [sum(cm.matrix[i]) for i in range(n)]
    col_sums = [sum(cm.matrix[i][j] for i in range(n)) for j in range(n)]
    pe = _safe_div(sum(row_sums[k] * col_sums[k] for k in range(n)), total * total)
    oa = _safe_div(cm.correct(), total)
    return _safe_div(oa - pe, 1.0 - pe)


def _average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks with tie-averaging — the standard input to a
    Mann-Whitney-U-based AUC so tied scores don't bias the result."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def _compute_roc(
    y_true_binary: Sequence[int], y_scores: Sequence[float]
) -> tuple[float, float, tuple[RocPoint, ...]]:
    """Returns ``(auc, optimal_threshold, roc_points)``.

    AUC via the Mann-Whitney-U / rank-sum formula — exact, and equivalent
    to trapezoidal-rule AUC-under-the-ROC-curve even with tied scores:

        AUC = (rank_sum(positives) - n_pos*(n_pos+1)/2) / (n_pos * n_neg)

    ROC points and the Youden's-J optimal threshold come from a separate
    sweep over each unique score value (descending), computing TPR/FPR at
    each — the same shape `core/validation.py`'s sklearn-backed version
    returned, just computed without the dependency.
    """
    n_pos = sum(1 for y in y_true_binary if y == 1)
    n_neg = len(y_true_binary) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5, 0.5, ()

    ranks = _average_ranks(list(y_scores))
    rank_sum_pos = sum(r for r, y in zip(ranks, y_true_binary, strict=False) if y == 1)
    auc = (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)

    thresholds = sorted(set(y_scores), reverse=True)
    points: list[RocPoint] = []
    best_j = -1.0
    best_threshold = thresholds[0] if thresholds else 0.5
    for t in thresholds:
        tp = sum(1 for s, y in zip(y_scores, y_true_binary, strict=False) if s >= t and y == 1)
        fp = sum(1 for s, y in zip(y_scores, y_true_binary, strict=False) if s >= t and y == 0)
        tpr = _safe_div(tp, n_pos)
        fpr = _safe_div(fp, n_neg)
        j = tpr - fpr
        if j > best_j:
            best_j = j
            best_threshold = t
        points.append(RocPoint(fpr=round(fpr, 6), tpr=round(tpr, 6), threshold=round(float(t), 6)))
    return round(auc, 6), round(float(best_threshold), 6), tuple(points)


def compute_metric_set(dataset: ValidationDataset) -> MetricSet:
    """The single entry point `application/handlers.py` calls: one
    `ValidationDataset` in, one fully-populated `MetricSet` out.

    Binary case (exactly 2 labels): precision/recall/specificity/F1 use the
    standard formulas against ``labels[1]`` as the positive class — matches
    `core/validation.py`'s `compute_classification_metrics` exactly.

    Multi-class case (3+ labels): precision/recall/F1 are macro-averaged
    across each label's one-vs-rest counts; `specificity` has no
    well-defined macro-average and is left ``None``.

    ROC/AUC (only when ``dataset.y_scores`` is provided): `y_true` is
    binarized by treating the lexicographically-last resolved label as
    "positive" — the same convention `build_confusion_matrix` already uses
    for `binary_counts()`, applied consistently here too.
    """
    cm = build_confusion_matrix(dataset.y_true, dataset.y_pred, dataset.labels)
    total = cm.total()
    overall_accuracy = round(_safe_div(cm.correct(), total), 6)
    kappa = round(_compute_kappa(cm), 6)

    precision: float | None
    recall: float | None
    specificity: float | None
    f1_score: float | None

    if len(cm.labels) == 2:
        counts = cm.binary_counts()
        assert counts is not None
        tp, fp, tn, fn = counts
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        specificity = _safe_div(tn, tn + fp)
        f1_score = _safe_div(2.0 * precision * recall, precision + recall)
    else:
        precisions, recalls, f1s = [], [], []
        for label in cm.labels:
            tp, fp, tn, fn = cm.per_class_counts(label)
            p = _safe_div(tp, tp + fp)
            r = _safe_div(tp, tp + fn)
            precisions.append(p)
            recalls.append(r)
            f1s.append(_safe_div(2.0 * p * r, p + r))
        precision = _mean(precisions)
        recall = _mean(recalls)
        f1_score = _mean(f1s)
        specificity = None

    auc: float | None = None
    optimal_threshold: float | None = None
    roc_points: tuple[RocPoint, ...] = ()
    if dataset.y_scores is not None and cm.labels:
        positive_label = cm.labels[-1]
        y_true_binary = [1 if v == positive_label else 0 for v in dataset.y_true]
        auc, optimal_threshold, roc_points = _compute_roc(y_true_binary, list(dataset.y_scores))

    return MetricSet(
        confusion_matrix=cm,
        sample_size=total,
        overall_accuracy=overall_accuracy,
        precision=round(precision, 6) if precision is not None else None,
        recall=round(recall, 6) if recall is not None else None,
        specificity=round(specificity, 6) if specificity is not None else None,
        f1_score=round(f1_score, 6) if f1_score is not None else None,
        kappa=kappa,
        auc=auc,
        optimal_threshold=optimal_threshold,
        roc_points=roc_points,
    )


def compute_verdict(metrics: MetricSet, thresholds: ValidationThresholds) -> Verdict:
    """ "Verdict is a pure function of metrics vs. declared thresholds"
    (Domain Model §1 row 14) — literally this function. Every declared
    (non-``None``) threshold must be met by the corresponding metric;
    an unset threshold is not checked at all. A `MetricSet` missing a
    metric that a threshold demands (e.g. `min_auc` declared but no
    `y_scores` were supplied) fails closed, not open.
    """
    checks = (
        (thresholds.min_overall_accuracy, metrics.overall_accuracy),
        (thresholds.min_precision, metrics.precision),
        (thresholds.min_recall, metrics.recall),
        (thresholds.min_f1_score, metrics.f1_score),
        (thresholds.min_auc, metrics.auc),
    )
    for threshold, value in checks:
        if threshold is not None and (value is None or value < threshold):
            return Verdict.FAIL
    return Verdict.PASS
