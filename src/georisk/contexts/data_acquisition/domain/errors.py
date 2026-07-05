"""Data Acquisition-specific domain errors — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import (
    IllegalStateTransitionError,
    NotFoundError,
    ValidationFailedError,
)


class DatasetSourceNotFoundError(NotFoundError):
    pass


class DatasetNotFoundError(NotFoundError):
    pass


class PredictorVariableNotFoundError(NotFoundError):
    pass


class VariableSelectionNotFoundError(NotFoundError):
    pass


class InvalidVariableSelectionError(ValidationFailedError):
    """A ``VariableSelection`` was created with no variables, or
    referenced a ``PredictorVariable`` that doesn't exist / isn't active."""


class AcquisitionJobNotFoundError(NotFoundError):
    pass


class InvalidAcquisitionJobError(ValidationFailedError):
    """An ``AcquisitionJob`` was scheduled against a ``DataProvider`` not
    in :data:`ACQUISITION_CAPABLE_PROVIDERS`, or a Local Upload job was
    scheduled without any raw content attached."""


class IllegalAcquisitionJobTransitionError(IllegalStateTransitionError):
    """``start()``/``complete()``/``fail()`` was called against an
    ``AcquisitionJob`` not currently in the state that transition
    requires (e.g. executing a job that already RAN)."""


class NoProviderRegisteredError(ValidationFailedError):
    """``ProviderRegistry.resolve(provider)`` found no
    ``AcquisitionProvider`` registered for that ``DataProvider`` — mirrors
    ``contexts.analysis``'s ``NoCalculatorRegisteredError``."""
