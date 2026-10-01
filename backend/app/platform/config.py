"""Application settings. The only place that reads configuration (env vars prefixed `PSA_`)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field
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
    log_level: Annotated[
        Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], BeforeValidator(str.upper)
    ] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
