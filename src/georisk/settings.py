"""Root application configuration.

One settings class, injected everywhere via ``get_settings()`` — nothing else
in this codebase reads ``os.environ`` directly. That single seam is what lets
tests override configuration cleanly (Implementation Bootstrap §11).
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://georisk:georisk_dev@localhost:5432/georisk"
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:6379/0"
    redis_cache_url: str = "redis://localhost:6379/1"
    redis_ratelimit_url: str = "redis://localhost:6379/2"

    # minio | s3 — two interchangeable backends behind one interface
    # (Infrastructure Architecture §12). Only "minio" is wired up in Sprint 0.
    storage_backend: Literal["minio", "s3"] = "minio"
    storage_endpoint_url: str = "http://localhost:9000"
    storage_access_key: str = "georisk"
    storage_secret_key: str = "georisk_dev_minio"
    storage_bucket_prefix: str = "firas-dev"

    # shared_schema | schema_per_tenant — Infrastructure Architecture §5.
    # Read from Sprint 0 onward; only "shared_schema" is actually implemented
    # until Roadmap Sprint 11 — see contexts/identity/README.md.
    tenancy_mode: Literal["shared_schema", "schema_per_tenant"] = "shared_schema"

    # `NoDecode` is required here: pydantic-settings' env/dotenv sources
    # otherwise try to `json.loads()` any non-str-typed field's raw string
    # BEFORE field validators ever run, so a plain comma-separated value
    # (exactly what .env.example/.env.production.example ship) would
    # raise a `SettingsError` on startup rather than reaching
    # `_split_comma_separated` below. Discovered only during real
    # production-deployment validation (every prior sprint's tests
    # constructed `Settings(...)` directly in Python with a real list,
    # never loaded this field from an actual `.env` file) — not caught by
    # 487 passing tests across Sprints 0-14, since none of them exercised
    # this code path.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    otel_exporter_endpoint: str | None = None
    otel_service_name: str = "georisk-api"

    # Identity context (Roadmap Sprint 1). The default below is explicitly
    # a development-only placeholder — production deployments MUST inject a
    # unique, high-entropy secret via the platform's secrets manager
    # (Infrastructure Architecture §12), never rely on this default; see
    # ``is_production`` guard in Settings validation below.
    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_ttl_seconds: int = 8 * 60 * 60  # 8 hours (API Resource Model §11)

    # Notification & Early Warning (Roadmap Sprint 11) — Email channel.
    # ``smtp_host=None`` means "not configured": the channel reports every
    # send as an honest, immediate failure rather than attempting a socket
    # connection that would only ever time out — no SMTP server exists in
    # this platform's development/test environments (the same "no
    # fabricated integration" discipline every other unconfigured external
    # dependency in this codebase already follows).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str = "alerts@georisk.local"
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = 5.0

    # Data Acquisition (Roadmap Sprint 13) — USGS/NASA/Copernicus, each
    # fetched via the same generic ``HttpAcquisitionProvider``.
    # ``*_api_base_url=None`` means "not configured": identical honest-
    # immediate-failure discipline as ``smtp_host`` above.
    usgs_api_base_url: str | None = None
    usgs_api_key: str | None = None
    nasa_api_base_url: str | None = None
    nasa_api_key: str | None = None
    copernicus_api_base_url: str | None = None
    copernicus_api_key: str | None = None
    acquisition_http_timeout_seconds: float = 30.0

    # Data Acquisition (Roadmap Sprint 14) — the real Google Earth Engine
    # connector. A GCP service account with the Earth Engine API enabled;
    # ``gee_service_account_email``/``gee_service_account_private_key``
    # default to ``None`` — identical "unconfigured means honest
    # immediate failure" discipline as ``smtp_host`` above. No such
    # credentials exist anywhere in this platform's sandboxed
    # development/test environments.
    gee_service_account_email: str | None = None
    gee_service_account_private_key: str | None = None
    gee_project_id: str | None = None

    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_default_secret_in_production(cls, value: str, info: ValidationInfo) -> str:
        # Cross-field validation (needs `environment`) is done in the model
        # validator below instead — pydantic field validators run in
        # declaration order and `environment` is declared first, so `info`
        # already has it in `info.data` by the time this runs.
        if (
            info.data.get("environment") == "production"
            and value == "dev-only-insecure-secret-change-me"
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a real secret in production — "
                "the development default is not permitted."
            )
        return value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
