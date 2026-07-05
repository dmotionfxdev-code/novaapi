"""``HazardStrategy``/``StageCalculator`` — the interface Platform
Architecture §6 calls "where the actual flood/fire/landslide/drought
science lives." Pure Protocols, no I/O, no framework imports: a concrete
``StageCalculator.compute()`` is fully unit-testable in isolation (Clean
Architecture's domain layer) exactly like every other pure function this
codebase has already ported (Sprint 4's ``metrics.compute_metric_set``).

Nothing under ``contexts.analysis.strategies.*`` may be imported from here
or anywhere else in ``domain/`` — dependencies point one way, inward, from
a strategy package to this generic interface, never back out to a specific
hazard product (Platform Architecture §2's stated rule, enforced by the
import-linter "domain layers stay pure" contract).
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    IndicatorSet,
    StageType,
)


class StageCalculator(Protocol):
    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet: ...

    @property
    def formula_version(self) -> str:
        """Identifies the exact methodology this calculator implements
        (Sprint 5.2, ``GEORISK_SCOPE_REALIGNMENT.md`` §6): a per-stage
        version tag, bumped whenever a formula changes in a way that
        alters computed results (e.g. FIRAS Risk's additive-EWM formula
        becoming multiplicative), so a ``StageResult`` stays traceable to
        exactly which formula generation produced it even after the
        platform corrects or replaces that formula."""
        ...


class HazardStrategy(Protocol):
    def supported_stages(self) -> frozenset[StageType]:
        """Which stages this hazard type participates in — FIRAS: 5 in
        this sprint's scope (Hazard, Exposure, Vulnerability, Risk,
        Resilience; Insecurity is folded into Vulnerability's calculator
        and Prediction/Validation aren't hazard-strategy stages)."""
        ...

    def get_calculator(self, stage_type: StageType) -> StageCalculator:
        """Resolves the pure domain function for one stage. Raises if
        ``stage_type`` isn't in ``supported_stages()`` — the caller
        (``StrategyRegistry.resolve``) is expected to check membership
        first and never call this with an unsupported stage."""
        ...

    def input_dependencies(self, stage_type: StageType) -> dict[StageType, dict[str, str]]:
        """Sprint 6 (WRRAS Scope Decision Log — architecture defect found
        while onboarding a second hazard type): declares which prior
        stages' ``StageResult`` indicators must be read and passed as raw
        inputs before ``get_calculator(stage_type).compute()`` runs.

        Maps ``prior_stage_type -> {source_indicator_code: target_input_key}``.
        ``RecordStageResultHandler`` fetches each ``prior_stage_type``'s
        latest COMPLETE result and copies each named indicator's value
        under its target key into the gathered inputs dict — mechanical,
        with no hazard-type-specific branching in the handler itself.

        Stages with no ``StageResult`` dependency at all — leaf stages
        that read raw external data via ``IndicatorInputProvider``
        instead (Hazard/Exposure/Vulnerability for every strategy so far)
        — return ``{}``.

        Before this method existed, the handler hardcoded FIRAS's exact
        indicator codes (``flood_hazard_index``, ``flood_insecurity_index``,
        ...) directly for Risk/Resilience, silently assuming there would
        only ever be one registrant. That was never exercised until
        WRRAS's Risk needed a different code (``wildfire_vulnerability_index``,
        not an insecurity index) and a different dependency shape — this
        method is the fix, applied once, for every future hazard type.
        """
        ...

    def historical_stages(self) -> frozenset[StageType]:
        """Which of this strategy's stages need EWM-style historical
        comparison data fetched (via ``StageResultRepository
        .list_historical_indicators``) before ``compute()`` runs.
        Stages outside this set never trigger that lookup — a hazard type
        that uses no EWM at all (WRRAS, per ``WRRAS_ARCHITECTURE_ALIGNMENT
        .md``) returns an empty ``frozenset()``, exactly like FIRAS's own
        non-EWM stages (Hazard, Exposure, Risk post-Sprint-5.2) do."""
        ...

    @property
    def strategy_version(self) -> str:
        """Identifies this whole strategy package's version (coarser-
        grained than a single calculator's ``formula_version``) — Sprint
        5.2's version-tracking requirement."""
        ...
