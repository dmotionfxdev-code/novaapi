"""Analysis-specific domain errors — subclass the shared_kernel hierarchy,
self-contained around the shared base classes (Sprint 1's established
pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import NotFoundError, ValidationFailedError


class StageResultNotFoundError(NotFoundError):
    pass


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
