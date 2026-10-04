"""Application settings. The only place that reads configuration (env vars prefixed `PSA_`)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PSA_", extra="ignore")

    env: Literal["local", "prod"] = Field(default="local", description="Deployment environment.")
    version: str = Field(default="0.0.0-dev", description="Build version, set at image build.")
    database_url: str = Field(
        default="postgresql+psycopg://psa:psa@localhost:5432/psa",
        description="SQLAlchemy URL; the psycopg 3 driver is used sync and async.",
    )
    migrations_database_url: str | None = Field(
        default=None,
        description=(
            "URL Alembic uses, as the schema owner role. Falls back to database_url when "
            "unset. The app itself connects as the least-privileged psa_app role."
        ),
    )
    db_connect_timeout_s: float = Field(default=2.0, gt=0)
    auth0_domain: str = Field(
        default="",
        description=(
            "Auth0 tenant domain, e.g. `example.eu.auth0.com`. Tokens must be issued by "
            "`https://{auth0_domain}/`; signing keys come from its JWKS endpoint."
        ),
    )
    auth0_audience: str = Field(
        default="", description="The Auth0 API identifier access tokens must carry in `aud`."
    )
    auth0_jwks_cache_lifespan_s: float = Field(
        default=300, gt=0, description="How long fetched JWKS signing keys are cached."
    )
    auth0_jwks_timeout_s: float = Field(
        default=5, gt=0, description="Timeout for one JWKS fetch from Auth0."
    )
    storage_dir: Path = Field(
        default=Path("var/files"),
        description=(
            "Root of the content-addressed file store (`platform.storage`): blobs live under "
            "`sha256/ab/cd/<sha256>`, upload temp files under `tmp/`. A volume in R1."
        ),
    )
    upload_max_bytes: int = Field(
        default=50 * 1024 * 1024,
        gt=0,
        description="Largest accepted upload in bytes (50 MB). Enforced by the API only.",
    )
    worker_poll_s: float = Field(
        default=1.0,
        gt=0,
        description="How long the worker sleeps (jittered ±20%) when no job is ready.",
    )
    worker_concurrency: int = Field(
        default=1,
        ge=1,
        le=1,
        description="Jobs one worker process runs at a time. Reserved: only 1 is supported.",
    )
    job_lease_s: float = Field(
        default=30.0,
        gt=0,
        description="How long a claim holds a job before another worker may reclaim it.",
    )
    job_heartbeat_s: float = Field(
        default=10.0,
        gt=0,
        description="How often a running job's lease is extended; at most job_lease_s / 2.",
    )
    log_level: Annotated[
        Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], BeforeValidator(str.upper)
    ] = "INFO"

    @model_validator(mode="after")
    def _heartbeat_inside_lease(self) -> "Settings":
        if self.job_heartbeat_s > self.job_lease_s / 2:
            raise ValueError("job_heartbeat_s must be at most half of job_lease_s")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
