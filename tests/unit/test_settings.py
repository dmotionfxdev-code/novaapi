"""Unit tests for Settings — pure logic, no I/O."""

from __future__ import annotations

import pytest

from georisk.settings import Settings

pytestmark = pytest.mark.unit


def test_cors_allowed_origins_splits_comma_separated_env_value() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        cors_allowed_origins="http://localhost:5173,http://localhost:8080",  # type: ignore[arg-type]
    )
    assert settings.cors_allowed_origins == ["http://localhost:5173", "http://localhost:8080"]


def test_cors_allowed_origins_accepts_a_real_list_unchanged() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        cors_allowed_origins=["http://localhost:5173"],
    )
    assert settings.cors_allowed_origins == ["http://localhost:5173"]


def test_is_production_true_only_in_production_environment() -> None:
    db_url = "postgresql+asyncpg://u:p@localhost:5432/db"
    dev = Settings(database_url=db_url, environment="development")
    # A real secret must be supplied for "production" — the insecure
    # development default is rejected by validation (Identity context,
    # Roadmap Sprint 1); see test_jwt_secret_key_rejects_dev_default_in_production.
    prod = Settings(
        database_url=db_url, environment="production", jwt_secret_key="a-real-production-secret"
    )
    assert dev.is_production is False
    assert prod.is_production is True


def test_jwt_secret_key_rejects_dev_default_in_production() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be set"):
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost:5432/db",
            environment="production",
            jwt_secret_key="dev-only-insecure-secret-change-me",
        )


def test_jwt_secret_key_dev_default_is_fine_outside_production() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db", environment="development"
    )
    assert settings.jwt_secret_key == "dev-only-insecure-secret-change-me"
