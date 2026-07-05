"""Prediction-specific domain errors — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import NotFoundError, ValidationFailedError


class PredictionRunNotFoundError(NotFoundError):
    pass


class VariableSelectionNotAvailableError(ValidationFailedError):
    """The referenced ``VariableSelection`` doesn't exist, isn't visible
    to this tenant, or isn't ``CONFIRMED`` yet — "Variables must be
    selected from VariableSelection" requires a real, confirmed
    selection, not an ad-hoc variable list."""


class SamplingCampaignNotAvailableError(ValidationFailedError):
    """The referenced ``SamplingCampaign`` doesn't exist, isn't visible
    to this tenant, or hasn't generated its sample points yet."""


class InsufficientObservationsError(ValidationFailedError):
    """Too few observations for the requested computation (correlation
    needs >= 2; MLR needs >= predictors + 2)."""


class MissingDependentVariableError(ValidationFailedError):
    """Multiple Linear Regression requires exactly one ``DEPENDENT``
    variable in the ``VariableSelection``."""
