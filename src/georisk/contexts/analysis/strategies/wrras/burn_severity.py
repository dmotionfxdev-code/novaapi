"""WRRAS Module 2 (partial) — Burn Severity Analysis. Optional, non-gating
supporting-analysis stage — classified B) Supporting Analysis Module in
``WRRAS_SCOPE_DECISION_LOG.md`` §3: the computation itself belongs here;
map/dashboard rendering of its outputs is a separate D) Reporting concern,
not built in this sprint. Never a ``required_predecessor`` of anything;
must not affect Risk.

Ported near-verbatim from the legacy system's ``apps/wrras/burn_severity
.py`` — specifically its satellite-band-derived indices (NBR/dNBR/RBR/
BAI), the specification's primary/recommended metric set. The
field-survey-based "Enhanced" functions (CBI/BSI/FVL/SBSI) are not ported
in this sprint; adding them later is an additive change to this same
calculator, not a platform change, matching the "strategy registration is
additive" property this whole sprint demonstrates.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)


def _nbr(nir: float, swir: float) -> float:
    denom = nir + swir
    return (nir - swir) / denom if denom != 0 else 0.0


def _bai(red: float, nir: float) -> float:
    denom = (0.1 - red) ** 2 + (0.06 - nir) ** 2
    return 1.0 / denom if denom != 0 else 0.0


def _validate_band(value: float, name: str) -> float:
    if not (0.0 <= value <= 1.0):
        raise InvalidIndicatorInputError(
            f"Band '{name}' reflectance must be in [0, 1], got {value}"
        )
    return float(value)


def compute_burn_severity(
    nir_pre: float,
    swir_pre: float,
    nir_post: float,
    swir_post: float,
    red_pre: float,
    red_post: float,
) -> dict[str, float]:
    """NBR = (NIR-SWIR)/(NIR+SWIR); dNBR = NBR_pre - NBR_post;
    RBR = dNBR/(NBR_pre+1.001); BAI = 1/((0.1-RED)^2+(0.06-NIR)^2)."""
    nir_pre = _validate_band(nir_pre, "nir_pre")
    swir_pre = _validate_band(swir_pre, "swir_pre")
    nir_post = _validate_band(nir_post, "nir_post")
    swir_post = _validate_band(swir_post, "swir_post")
    red_pre = _validate_band(red_pre, "red_pre")
    red_post = _validate_band(red_post, "red_post")

    nbr_pre = round(_nbr(nir_pre, swir_pre), 4)
    nbr_post = round(_nbr(nir_post, swir_post), 4)
    dnbr = round(nbr_pre - nbr_post, 4)
    rbr = round(dnbr / (nbr_pre + 1.001), 4)

    bai_pre = round(_bai(red_pre, nir_pre), 4)
    bai_post = round(_bai(red_post, nir_post), 4)
    dbai = round(bai_post - bai_pre, 4)

    return {
        "nbr_pre": nbr_pre,
        "nbr_post": nbr_post,
        "dnbr": dnbr,
        "rbr": rbr,
        "bai_pre": bai_pre,
        "bai_post": bai_post,
        "dbai": dbai,
    }


class WRRASBurnSeverityCalculator:
    formula_version = "burn-severity-spectral-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        result = compute_burn_severity(
            nir_pre=inputs["nir_pre"],
            swir_pre=inputs["swir_pre"],
            nir_post=inputs["nir_post"],
            swir_post=inputs["swir_post"],
            red_pre=inputs["red_pre"],
            red_post=inputs["red_post"],
        )
        indicators = tuple(
            Indicator(code=key, value=value, unit="index") for key, value in result.items()
        )
        return IndicatorSet(indicators=indicators)
