"""Value objects for the Analysis Engine (Domain Model §1 row 11:
``StageResult``'s ``IndicatorSet``/``ComputationSnapshot``/``ConfidenceTier``).

``StageType``/``HazardType`` here are deliberately independent, locally
defined enums, not imports of
``contexts.assessment.domain.workflow_value_objects.StageType``/
``value_objects.HazardType`` — the import-linter's peer-independence
contract forbids ``analysis`` from importing ``assessment`` at all, and
Domain Model §7 frames this relationship as Assessment "publishing" the
stage-and-status vocabulary as data (plain strings), not as a shared Python
type every context imports. The string VALUES are kept identical to
Assessment's own enum so a `stage_type`/`hazard_type` string flows losslessly
between the two contexts; only the composition-root glue (outside both
contexts) ever holds both enum types at once and converts between them —
the same pattern already established for Validation's ``SubjectType`` in
Sprint 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class StageResultId(TypedId):
    pass


class HazardType(StrEnum):
    """Mirrors ``contexts.assessment.domain.value_objects.HazardType``'s
    string values exactly — see this module's docstring for why it's a
    separate type rather than an import.
    """

    FLOOD = "FLOOD"
    WILDFIRE = "WILDFIRE"
    DROUGHT = "DROUGHT"
    LANDSLIDE = "LANDSLIDE"


class StageType(StrEnum):
    """Mirrors ``contexts.assessment.domain.workflow_value_objects.StageType``'s
    string values exactly, including ``RESILIENCE`` (Sprint 5) and the
    three optional, non-gating WRRAS supporting-analysis stages (Sprint 6:
    ``FIRE_REGIME``, ``BURN_OCCURRENCE_PROBABILITY``, ``BURN_SEVERITY`` —
    see the assessment-side enum's docstring for why they're non-gating)
    — see this module's docstring for why it's a separate type rather
    than an import.
    """

    HAZARD = "HAZARD"
    EXPOSURE = "EXPOSURE"
    VULNERABILITY = "VULNERABILITY"
    RISK = "RISK"
    RESILIENCE = "RESILIENCE"
    VALIDATION = "VALIDATION"
    FIRE_REGIME = "FIRE_REGIME"
    BURN_OCCURRENCE_PROBABILITY = "BURN_OCCURRENCE_PROBABILITY"
    BURN_SEVERITY = "BURN_SEVERITY"


class StageResultStatus(StrEnum):
    """Deliberately just two states — same reasoning as Sprint 4's
    ``ValidationRunStatus``: every calculator in this sprint
    (``strategies.firas``) is a synchronous, pure-Python function with no
    async job in between "asked to compute" and "done."
    """

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ConfidenceTier(StrEnum):
    """Domain Model §2: ``LOW | MODERATE | HIGH``, derived from sample size
    (n=1→LOW, n=2-4→MODERATE, n≥5→HIGH) — the exact tiers
    ``core.ewm.confidence_tier`` already used in the legacy system,
    formalized as this platform's ``ConfidenceTierPolicy`` (Platform
    Architecture §3): "a pure function of sample count," used identically
    regardless of which hazard strategy's calculator produced the count.
    """

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


def confidence_tier_for_sample_size(n: int) -> ConfidenceTier:
    if n >= 5:
        return ConfidenceTier.HIGH
    if n >= 2:
        return ConfidenceTier.MODERATE
    return ConfidenceTier.LOW


@dataclass(frozen=True, slots=True)
class Indicator:
    """Domain Model §2: ``Indicator { code, value, unit, subIndex }``."""

    code: str
    value: float
    unit: str = ""
    sub_index: str | None = None


@dataclass(frozen=True, slots=True)
class IndicatorSet:
    """Domain Model §2: "ordered collection of Indicator." Lookups go
    through ``get``/``value``, never list indexing, so callers don't need
    to know each calculator's exact ordering.
    """

    indicators: tuple[Indicator, ...] = field(default_factory=tuple)

    def get(self, code: str) -> Indicator | None:
        for indicator in self.indicators:
            if indicator.code == code:
                return indicator
        return None

    def value(self, code: str) -> float | None:
        indicator = self.get(code)
        return indicator.value if indicator is not None else None

    def as_dict(self) -> dict[str, float]:
        return {i.code: i.value for i in self.indicators}


@dataclass(frozen=True, slots=True)
class ComputationSnapshot:
    """Domain Model §2: "the exact inputs ... used to produce a
    StageResult, frozen at compute time." No AOI/dataset versions yet
    (Geospatial/Data Acquisition don't exist) — ``inputs`` holds whatever
    raw values a ``StageCalculator`` actually consumed (its own raw
    indicators, and/or prior-stage ``IndicatorSet`` values it read),
    ``historical_count`` records how many past observations (if any) fed
    into an EWM-weighted calculation, for auditability.

    ``historical`` carries the comparison-set records an EWM-driven
    calculator needs at compute time (Sprint 5.2), deliberately kept
    separate from ``inputs`` rather than merged into it: Sprint 5
    originally stashed the fetched historical list under
    ``inputs["historical"]`` before persisting, which meant every saved
    snapshot embedded a growing, self-referential copy of its own
    comparison set. Only ``inputs`` and ``historical_count`` are ever
    persisted (see ``infrastructure/mappers.py``) — ``historical`` itself
    is a compute-time-only field, never round-tripped from storage.
    """

    inputs: dict
    historical: tuple[dict, ...] = field(default_factory=tuple)
    historical_count: int = 0
