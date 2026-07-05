"""Multiple Linear Regression Engine (Sprint 8 requirement #3) — ported
near-verbatim from the legacy system's shared ``core/mlr.py`` ("shared
computation for FIRAS and WRRAS MLR modules"): ``Y = β0 + β1X1 + ... +
βnXn + ε``, solved via the normal equations (Gauss-Jordan matrix
inversion), pure Python, no numpy dependency — matching this codebase's
established policy.

"Do not hardcode predictor variables": ``feature_matrix``/``feature_names``
are however many variables the caller's ``VariableSelection`` resolved to
— nothing here assumes a fixed variable count or name.
"""

from __future__ import annotations

import math

from georisk.contexts.prediction.domain.errors import InsufficientObservationsError


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    rows_a, cols_a = len(a), len(a[0])
    cols_b = len(b[0])
    return [
        [sum(a[i][k] * b[k][j] for k in range(cols_a)) for j in range(cols_b)]
        for i in range(rows_a)
    ]


def _transpose(m: list[list[float]]) -> list[list[float]]:
    return [[m[j][i] for j in range(len(m))] for i in range(len(m[0]))]


def _mat_inv(m: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inversion for small square matrices."""
    n = len(m)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        p = aug[col][col]
        if abs(p) < 1e-12:
            raise ValueError("Matrix is singular — predictor variables may be collinear")
        aug[col] = [v / p for v in aug[col]]
        for row in range(n):
            if row != col:
                f = aug[row][col]
                aug[row] = [aug[row][k] - f * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


def _t_distribution_two_tailed_p(t: float, df: int) -> float:
    """Two-tailed p-value from the t-distribution via the regularized
    incomplete beta function (Numerical Recipes' continued-fraction
    approximation) — the same approximation the legacy ``core/mlr.py``
    used, ported unchanged."""
    x = df / (df + t * t)
    a, b = df / 2.0, 0.5
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return front * h


class MlrFitResult:
    """Plain result carrier — the domain VO layer
    (``value_objects.RegressionResult``) is built from this by the
    application handler; kept separate so this module stays pure
    numeric computation with no dependency on the VO/entity layer.
    """

    __slots__ = (
        "intercept",
        "coefficients",
        "standardized_coefficients",
        "standard_errors",
        "t_statistics",
        "p_values",
        "r2",
        "adjusted_r2",
        "rmse",
        "mae",
        "mse",
        "f_statistic",
        "n_observations",
    )

    intercept: float
    coefficients: list[float]
    standardized_coefficients: list[float]
    standard_errors: list[float]
    t_statistics: list[float]
    p_values: list[float]
    r2: float
    adjusted_r2: float
    rmse: float
    mae: float
    mse: float
    f_statistic: float
    n_observations: int

    def __init__(
        self,
        *,
        intercept: float,
        coefficients: list[float],
        standardized_coefficients: list[float],
        standard_errors: list[float],
        t_statistics: list[float],
        p_values: list[float],
        r2: float,
        adjusted_r2: float,
        rmse: float,
        mae: float,
        mse: float,
        f_statistic: float,
        n_observations: int,
    ) -> None:
        self.intercept = intercept
        self.coefficients = coefficients
        self.standardized_coefficients = standardized_coefficients
        self.standard_errors = standard_errors
        self.t_statistics = t_statistics
        self.p_values = p_values
        self.r2 = r2
        self.adjusted_r2 = adjusted_r2
        self.rmse = rmse
        self.mae = mae
        self.mse = mse
        self.f_statistic = f_statistic
        self.n_observations = n_observations


def compute_multiple_linear_regression(
    feature_matrix: list[list[float]], y_values: list[float], feature_names: list[str]
) -> MlrFitResult:
    """Fits ``Y = β0 + β1X1 + ... + βkXk`` via ordinary least squares.

    Parameters
    ----------
    feature_matrix : shape (n, k) — predictor values, in ``feature_names`` order.
    y_values       : shape (n,) — the dependent variable's observed values.
    feature_names  : length k — "Do not hardcode predictor variables":
        whatever the caller's ``VariableSelection`` resolved to.
    """
    n = len(y_values)
    k = len(feature_names)

    if n < k + 2:
        raise InsufficientObservationsError(
            f"Need at least {k + 2} observations for {k} predictors (have {n})"
        )

    x_aug = [[1.0, *row] for row in feature_matrix]
    xt = _transpose(x_aug)
    xtx = _mat_mul(xt, x_aug)
    xty = [_dot(xt[i], y_values) for i in range(k + 1)]

    xtx_inv = _mat_inv(xtx)

    betas = [sum(xtx_inv[i][j] * xty[j] for j in range(k + 1)) for i in range(k + 1)]
    intercept = betas[0]
    coefficients = betas[1:]

    y_hat = [sum(betas[j] * x_aug[i][j] for j in range(k + 1)) for i in range(n)]
    residuals = [y_values[i] - y_hat[i] for i in range(n)]

    y_mean = _mean(y_values)
    ss_res = sum(r**2 for r in residuals)
    ss_tot = sum((y - y_mean) ** 2 for y in y_values)

    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    adjusted_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - k - 1) if n > k + 1 else 0.0

    mse = ss_res / (n - k - 1)
    standard_errors = [math.sqrt(max(0.0, mse * xtx_inv[i][i])) for i in range(k + 1)]

    df = n - k - 1
    t_statistics = [
        betas[i] / standard_errors[i] if standard_errors[i] > 1e-12 else 0.0
        for i in range(k + 1)
    ]
    p_values = [_t_distribution_two_tailed_p(abs(t), df) for t in t_statistics]

    rmse = math.sqrt(ss_res / n)
    mae = sum(abs(r) for r in residuals) / n

    x_stds = []
    for j in range(k):
        column = [feature_matrix[i][j] for i in range(n)]
        column_mean = _mean(column)
        column_variance = sum((v - column_mean) ** 2 for v in column) / max(1, n - 1)
        x_stds.append(math.sqrt(column_variance))
    y_std = math.sqrt(sum((y - y_mean) ** 2 for y in y_values) / max(1, n - 1))
    standardized_coefficients = [
        coefficients[j] * x_stds[j] / y_std if y_std > 1e-9 and x_stds[j] > 1e-9 else 0.0
        for j in range(k)
    ]

    ms_regression = (ss_tot - ss_res) / k if k > 0 else 0.0
    f_statistic = ms_regression / mse if mse > 1e-12 else 0.0

    return MlrFitResult(
        intercept=round(intercept, 6),
        coefficients=[round(c, 6) for c in coefficients],
        standardized_coefficients=[round(c, 6) for c in standardized_coefficients],
        standard_errors=[round(se, 6) for se in standard_errors[1:]],
        t_statistics=[round(t, 4) for t in t_statistics[1:]],
        p_values=[round(p, 6) for p in p_values[1:]],
        r2=round(r2, 6),
        adjusted_r2=round(adjusted_r2, 6),
        rmse=round(rmse, 6),
        mae=round(mae, 6),
        mse=round(mse, 6),
        f_statistic=round(f_statistic, 4),
        n_observations=n,
    )
