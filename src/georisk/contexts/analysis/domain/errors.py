"""Analysis-specific domain errors — subclass the shared_kernel hierarchy,
self-contained around the shared base classes (Sprint 1's established
pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import NotFoundError, ValidationFailedError


class StageResultNotFoundError(NotFoundError):
    pass


class RiskLayerNotFoundError(NotFoundError):
    """No ``RiskLayer`` has ever been generated for this assessment — a
    real Shapefile-sourced geometry dataset (Sprint B) may never have
    been cataloged for this tenant's hazard type, or the RISK stage
    hasn't completed yet. Never fabricated in its place."""


class NoCalculatorRegisteredError(ValidationFailedError):
    """``StrategyRegistry.resolve(hazard_type, stage_type)`` found no
    ``HazardStrategy`` registered for ``hazard_type``, or that strategy
    doesn't support ``stage_type``.
    """


class InvalidIndicatorInputError(ValidationFailedError):
    """A calculator's raw inputs failed its own validation (e.g. weights
    not summing to 1.0, a ratio outside [0, 1]) — surfaced as a domain
    error, not an uncaught exception from deep inside a formula module.
    """


class RiskLayerGenerationError(ValidationFailedError):
    """The Risk Layer Generator was asked to generate a layer from a
    ``StageResult`` that can't supply one — not yet COMPLETE, not a RISK
    stage, or (defensively) a COMPLETE RISK result with no indicators at
    all. Never fabricates a risk index to work around this."""
