"""Validation-specific domain errors — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern, not shared with other contexts' same-shaped errors).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import NotFoundError, ValidationFailedError


class ValidationRunNotFoundError(NotFoundError):
    pass


class InvalidValidationDatasetError(ValidationFailedError):
    pass
