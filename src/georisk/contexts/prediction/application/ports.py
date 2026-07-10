"""Ports the Prediction context needs from its peers — Data Acquisition's
``VariableSelection``/``PredictorVariable`` registry and Geospatial's
``SamplingCampaign``. Prediction's own bounded context may not import
either peer directly (import-linter's independence contract), so these
Protocols are the seam: a composition-root module (``api/``, outside all
three contexts — the same role ``api/workflow_stage_executors.py``
already plays for Assessment/Analysis/Validation) implements
``VariableSelectionReader``/``SamplingCampaignReader`` by calling those
contexts' own read-only query classes directly, since composition roots
are exempt from the peer-independence contract by design.

``PredictionDataProvider`` is different in kind: it isn't a bridge to
another context's *real* data (no context anywhere in this platform has
real per-observation predictor values yet — Data Acquisition's
``Dataset``/``PredictorVariable`` are catalog/registry metadata, not
actual raster/tabular payloads; Sprint 7 built the catalog, not the GEE
pipeline that would populate it). ``StubPredictionDataProvider`` is this
sprint's honest placeholder, the identical pattern already used for
``StubIndicatorInputProvider`` (Sprint 5) and
``StubValidationSubjectResolver`` (Sprint 4): it proves the
correlation/MLR computation pipeline is wired correctly against
plausible, non-trivial synthetic data, without pretending this platform
has real sensor/satellite data feeding these variables yet.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PredictorVariableInfo:
    """The published shape Data Acquisition's ``PredictorVariable``
    resolves to for Prediction's purposes — deliberately not that
    context's own domain entity (translated at the composition-root
    boundary), so a change to Data Acquisition's internals doesn't force
    a change here."""

    predictor_variable_id: str
    code: str
    name: str
    variable_role: str
    value_min: float | None
    value_max: float | None


@dataclass(frozen=True, slots=True)
class VariableSelectionInfo:
    variable_selection_id: str
    status: str
    hazard_type: str | None
    variables: tuple[PredictorVariableInfo, ...]


class VariableSelectionReader(Protocol):
    async def get_selection(
        self, *, tenant_id: str, variable_selection_id: str
    ) -> VariableSelectionInfo | None: ...


class SamplingCampaignReader(Protocol):
    async def get_sample_count(
        self, *, tenant_id: str, sampling_campaign_id: str
    ) -> int | None:
        """Number of generated ``SamplePoint``s — ``None`` if the
        campaign doesn't exist, isn't visible to this tenant, or hasn't
        generated its points yet."""
        ...


class PredictionDataProvider(Protocol):
    async def generate_observations(
        self,
        *,
        tenant_id: str,
        hazard_type: str | None,
        variables: tuple[PredictorVariableInfo, ...],
        sample_count: int,
        seed: int,
    ) -> tuple[dict[str, float], ...]:
        """One flat ``{variable_code: value}`` dict per observation,
        covering every variable in ``variables`` (dependent included).
        ``tenant_id``/``hazard_type`` (the confirmed ``VariableSelection``'s
        own hazard_type, Sprint A) let a real implementation scope its
        lookup to this tenant's own completed Analysis history for this
        specific hazard strategy — ``StubPredictionDataProvider`` below
        ignores both, since its synthetic rows need no such scoping."""
        ...


_DEFAULT_RANGE = (0.0, 1.0)


class StubPredictionDataProvider:
    """Synthesizes ``sample_count`` observations, deterministic given
    ``seed``: each independent/derived/control variable is drawn
    uniformly from its own ``(value_min, value_max)`` (defaulting to
    [0, 1] when unset); any ``DEPENDENT`` variable is synthesized as a
    noisy average of the independent variables' *normalized* positions
    within their own ranges, remapped into the dependent's range — the
    same "baseline formula + noise" approach Sprint 5/6's synthetic AI-
    predictor training data already used, so correlation/MLR results are
    genuinely non-trivial rather than pure noise.
    """

    async def generate_observations(
        self,
        *,
        tenant_id: str,
        hazard_type: str | None,
        variables: tuple[PredictorVariableInfo, ...],
        sample_count: int,
        seed: int,
    ) -> tuple[dict[str, float], ...]:
        rng = random.Random(seed)
        independent = [v for v in variables if v.variable_role != "DEPENDENT"]
        dependent = [v for v in variables if v.variable_role == "DEPENDENT"]

        rows = []
        for _ in range(sample_count):
            row: dict[str, float] = {}
            normalized_values = []
            for variable in independent:
                low, high = variable.value_min, variable.value_max
                if low is None or high is None or high <= low:
                    low, high = _DEFAULT_RANGE
                value = rng.uniform(low, high)
                row[variable.code] = round(value, 6)
                normalized_values.append((value - low) / (high - low) if high > low else 0.5)

            if dependent and normalized_values:
                signal = sum(normalized_values) / len(normalized_values)
                noise = rng.gauss(0.0, 0.08)
                normalized_dependent = max(0.0, min(1.0, signal + noise))
                for variable in dependent:
                    low, high = variable.value_min, variable.value_max
                    if low is None or high is None or high <= low:
                        low, high = _DEFAULT_RANGE
                    row[variable.code] = round(low + normalized_dependent * (high - low), 6)

            rows.append(row)
        return tuple(rows)
