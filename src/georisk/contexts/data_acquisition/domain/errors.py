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


# --- Sprint B: real ESRI Shapefile ingestion ---


class IncompleteShapefileDatasetError(ValidationFailedError):
    """A Shapefile upload's ZIP archive is missing one or more of the four
    required components (``.shp``/``.shx``/``.dbf``/``.prj``), contains no
    ``.shp`` at all, or contains more than one — the message always names
    exactly which component(s) are missing/ambiguous, never a generic
    "invalid shapefile"."""


class CorruptedShapefileError(ValidationFailedError):
    """The archive has all four required components by name, but the real
    GIS library (pyogrio/GDAL) could not genuinely parse them as a
    Shapefile — covers both a wholesale-corrupted ``.shp``/``.shx`` and a
    malformed ``.dbf`` attribute table GDAL can't recover a consistent
    schema from."""


class InvalidShapefileCrsError(ValidationFailedError):
    """The ``.prj`` component is missing, empty, or GDAL could not resolve
    its WKT to any recognized coordinate reference system."""


class UnsupportedShapefileGeometryError(ValidationFailedError):
    """The archive's actual per-feature geometry type (as genuinely read
    from each feature's WKB, not just the Shapefile header's shape-type
    code) is not one of the geometry types this platform supports
    (Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon), or
    features disagree with each other about their geometry type."""


class EmptyShapefileDatasetError(ValidationFailedError):
    """The archive parses cleanly but contains zero features — nothing
    for Analysis to ever read, so cataloguing it would be pointless."""
