"""Sprint D — unit tests for the ``gen``/``jti`` claims ``JwtAccessTokenIssuer``
now embeds/extracts (the mechanics genuine access-token revocation is built
on: ``get_current_claims`` compares a decoded token's ``token_generation``
against the user's current counter, and its ``jti`` against the logout
denylist). Pure JWT encode/decode — no database needed.
"""

from __future__ import annotations

import time

import jwt
import pytest

from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import (
    PermissionCode,
    RoleName,
    TenantId,
    UserId,
)
from georisk.contexts.identity.infrastructure.security import JwtAccessTokenIssuer
from georisk.shared_kernel.errors import AuthenticationFailedError

pytestmark = pytest.mark.unit

_ISSUER = JwtAccessTokenIssuer(secret_key="test-secret", algorithm="HS256", ttl_seconds=3600)


def _claims(*, token_generation: int = 0) -> AccessTokenClaims:
    return AccessTokenClaims(
        user_id=UserId.new(),
        tenant_id=TenantId.new(),
        role_name=RoleName.ANALYST,
        permissions=frozenset({PermissionCode.ASSESSMENT_VIEW}),
        token_generation=token_generation,
    )


def test_issued_token_embeds_current_generation_and_a_fresh_jti() -> None:
    issued = _ISSUER.issue(_claims(token_generation=3))
    decoded = _ISSUER.decode(issued.token)
    assert decoded.token_generation == 3
    assert decoded.jti  # non-empty, uuid4-shaped
    assert len(decoded.jti) == 36


def test_two_tokens_issued_for_the_same_user_get_different_jtis() -> None:
    claims = _claims()
    first = _ISSUER.decode(_ISSUER.issue(claims).token)
    second = _ISSUER.decode(_ISSUER.issue(claims).token)
    assert first.jti != second.jti


def test_decode_defaults_generation_to_zero_for_a_pre_sprint_d_token() -> None:
    """A token minted before this sprint (no ``gen`` claim at all) must
    decode as generation 0 — matching every already-migrated user row's
    ``token_generation`` default, so no one is silently logged out the
    moment this deployment ships.
    """
    now = int(time.time())
    legacy_payload = {
        "sub": str(UserId.new()),
        "tenant_id": str(TenantId.new()),
        "role": RoleName.ANALYST.value,
        "permissions": [],
        "type": "access",
        "iat": now,
        "exp": now + 3600,
        "jti": "legacy-jti",
        # deliberately no "gen" claim
    }
    legacy_token = jwt.encode(legacy_payload, "test-secret", algorithm="HS256")
    decoded = _ISSUER.decode(legacy_token)
    assert decoded.token_generation == 0


def test_decode_expiry_returns_exp_even_slightly_in_the_past() -> None:
    short_lived_issuer = JwtAccessTokenIssuer(
        secret_key="test-secret", algorithm="HS256", ttl_seconds=-1
    )
    issued = short_lived_issuer.issue(_claims())
    # The token is already expired (ttl_seconds=-1) — ordinary decode()
    # correctly rejects it...
    with pytest.raises(AuthenticationFailedError):
        short_lived_issuer.decode(issued.token)
    # ...but decode_expiry() still returns its (past) expiry, needed so
    # logout can revoke an access token that expires in the same instant
    # logout is called, rather than erroring out.
    expiry = short_lived_issuer.decode_expiry(issued.token)
    assert expiry.timestamp() <= time.time()
