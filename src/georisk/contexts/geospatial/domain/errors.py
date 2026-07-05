"""Geospatial-specific domain errors — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import NotFoundError, ValidationFailedError


class AoiNotFoundError(NotFoundError):
    pass


class SamplingCampaignNotFoundError(NotFoundError):
    pass


class InvalidGeometryError(ValidationFailedError):
    """A supplied GeoJSON geometry failed structural validation (not a
    Polygon/MultiPolygon, an unclosed ring, too few positions)."""


class SamplePointOutsideAoiError(ValidationFailedError):
    """A generated or supplied sample point falls outside its campaign's
    AOI geometry — Domain Model §1 row 4's invariant: "Every SamplePoint
    must fall within the referenced AOI's geometry."""


class SamplingNotConfiguredError(ValidationFailedError):
    """``GenerateSamplePoints`` was requested for a campaign that hasn't
    been configured yet, or has already been generated."""
