"""Small application-layer policies shared by several command handlers —
not aggregate invariants (those live on the entities themselves), but
input-validation-before-touching-an-aggregate policy (Application Layer §2
pipeline step 1/6).
"""

from __future__ import annotations

from georisk.contexts.identity.domain.errors import WeakPasswordError

_MIN_PASSWORD_LENGTH = 12


class PasswordPolicy:
    """Length over complexity rules — current OWASP guidance favors a
    minimum-length requirement over mandated character classes, which
    empirically push users toward predictable substitutions (``P@ssw0rd``)
    rather than genuinely stronger passwords.
    """

    @staticmethod
    def validate(password: str) -> None:
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise WeakPasswordError(
                f"Password must be at least {_MIN_PASSWORD_LENGTH} characters long"
            )
