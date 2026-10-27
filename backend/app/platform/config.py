"""Application settings. The only place that reads configuration (env vars prefixed `PSA_`)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.platform.model_gateway.profiles import EMBED_PROFILES, MODEL_PROFILES

DEFAULT_DOWNLOAD_SIGNING_KEY = "local-dev-download-signing-key-change-me"
"""The local-only signing key; `prod` refuses to start with it."""


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
    actuals_import_max_bytes: int = Field(
        default=5 * 1024 * 1024,
        gt=0,
        description=(
            "Largest accepted Actuals import file (.xlsx or .csv) in bytes (5 MB, Story 10.2). "
            "Enforced by the API only."
        ),
    )
    knowledge_stale_months: int = Field(
        default=12,
        ge=1,
        le=120,
        description=(
            "A Knowledge Source whose last-reviewed date is more than this many months ago "
            "is flagged stale. The flag is derived, never stored."
        ),
    )
    knowledge_chunk_chars: int = Field(
        default=1500,
        ge=200,
        le=8000,
        description=(
            "Target (and largest) size of a Knowledge chunk in characters (code points). "
            "Chunks follow headings and paragraphs; a longer section is split with overlap."
        ),
    )
    knowledge_chunk_overlap_chars: int = Field(
        default=200,
        ge=0,
        description=(
            "Characters a chunk repeats from the end of the previous one when a section is "
            "split. Must be less than half of knowledge_chunk_chars."
        ),
    )
    download_signing_key: str = Field(
        default=DEFAULT_DOWNLOAD_SIGNING_KEY,
        min_length=16,
        description=(
            "Secret that signs short-lived download links (`platform.downloads`, e.g. for "
            "earlier Knowledge Source versions). Set a random value outside local."
        ),
    )
    download_link_ttl_s: int = Field(
        default=300, ge=1, le=3600, description="How long a signed download link works."
    )
    worker_poll_s: float = Field(
        default=1.0,
        gt=0,
        description="How long the worker sleeps (jittered ±20%) when no job is ready.",
    )
    worker_alive_file: Path | None = Field(
        default=None,
        description=(
            "When set, the worker touches this file every few seconds while it runs; the "
            "container healthcheck treats a stale file as a hung worker."
        ),
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
    parse_timeout_s: float = Field(
        default=120.0,
        gt=0,
        le=600,
        description=(
            "Wall-clock limit for parsing one Source file in its child process; past it the "
            "child is killed and the job retried. On Linux it also sets the CPU-time limit."
        ),
    )
    parse_max_memory_mb: int = Field(
        default=1024,
        ge=64,
        description="Address-space limit (RLIMIT_AS) for the parse child process, Linux only.",
    )
    ollama_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Base URL of the Ollama server the ModelGateway calls (host Ollama in R1).",
    )
    openai_base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        description=(
            "Base URL (the `/v1` root) of the OpenAI-compatible server that profiles with "
            "provider `openai` call at `/chat/completions`, e.g. vLLM. The default is host "
            "Ollama's own `/v1` endpoint."
        ),
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Optional bearer key for the OpenAI-compatible server. When set, every request "
            "sends `Authorization: Bearer <key>`; when unset, no auth header is sent."
        ),
    )
    openai_model: str | None = Field(
        default=None,
        description=(
            "Optional model id that every profile with provider `openai` sends instead of its "
            "own (e.g. `gpt-4.1` with `openai-chat`), so the model is a `.env` change. Empty "
            "or unset keeps the profile's model. Ollama profiles ignore it."
        ),
    )
    openai_reasoning_effort: str | None = Field(
        default=None,
        description=(
            "Set when the `openai`-provider model is a reasoning model (OpenAI's o-series, "
            "GPT-5): requests then send this `reasoning_effort` (e.g. `low`, `medium`, `high`) "
            "and no `temperature`, which those models reject. Empty or unset: a regular model."
        ),
    )
    model_profile_chat: str = Field(
        default="demo-chat",
        description=(
            "Named model profile (`app.platform.model_gateway.profiles`) used for chat calls. "
            "`demo-chat` sends prompt text to Ollama's cloud: sample or anonymised data only."
        ),
    )
    model_profile_embed: str = Field(
        default="bge-m3",
        description=(
            "Named embedding profile (`profiles.EMBED_PROFILES`) for Knowledge chunks and "
            "search queries. Changing it needs a re-embed: search only compares vectors of "
            "the active profile."
        ),
    )
    model_slots: int = Field(
        default=3,
        ge=1,
        description="Concurrent model calls per process; must be <= OLLAMA_NUM_PARALLEL.",
    )
    model_max_retries: int = Field(
        default=2,
        ge=0,
        description="Extra attempts after a model reply that fails schema validation.",
    )
    model_timeout_s: float = Field(
        default=120.0,
        gt=0,
        description="Default timeout for one model request (each attempt), in seconds.",
    )
    research_allowlist_path: Path | None = Field(
        default=None,
        description=(
            "The research allowlist (`ops/research-allowlist.yaml`: version, topics -> hosts) "
            "the ToolGateway's research fetch checks every URL and redirect against (Story "
            "5.4). Unset or missing: every research fetch is denied."
        ),
    )
    research_fetch_timeout_s: float = Field(
        default=10.0,
        gt=0,
        le=120,
        description="Wall-clock limit of one research fetch, every redirect hop included.",
    )
    research_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        gt=0,
        description="Largest research page body in bytes (2 MiB), counted while streaming.",
    )
    review_reminder_days: int = Field(
        default=3,
        ge=1,
        le=365,
        description=(
            "Days between reminders about a pending Review Request (Story 9.2): the daily "
            "`reviews.send_reminders` job gives the reviewer an Inbox reminder once the "
            "request is 1, 2, 3, … intervals old."
        ),
    )
    tool_denial_alert_threshold: int = Field(
        default=3,
        ge=0,
        le=10_000,
        description=(
            "Denied ToolGateway calls a run may have before an alert (Story 7.4): the first "
            "denial past it traces `platform.tool_call.denial_threshold_exceeded` and queues "
            "one alert email for the run."
        ),
    )
    resend_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Resend API key for alert emails (Story 7.4). Unset or blank: alert jobs log a "
            "warning and send nothing."
        ),
    )
    alert_email_from: str | None = Field(
        default=None,
        description="The sender of alert emails, e.g. `PSA Alerts <alerts@example.com>`.",
    )
    alert_email_to: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Alert email recipients, a comma-separated list.",
    )
    web_base_url: str = Field(
        default="http://localhost:3000",
        description="The web app's base URL, for links in alert emails.",
    )
    eval_database_url: str | None = Field(
        default=None,
        description=(
            "The isolated evaluation database `make eval` runs the reference set in, as the "
            "app role (Story 7.6). Must name a different database from database_url; the "
            "harness refuses to run without it. Every eval resets it."
        ),
    )
    eval_migrations_database_url: str | None = Field(
        default=None,
        description=(
            "URL Alembic uses to reset the evaluation database (`downgrade base`, then "
            "`upgrade head`), as its schema owner. Required by `make eval`."
        ),
    )
    cost_per_gpu_second_minor: int = Field(
        default=0,
        ge=0,
        description="Cost of one GPU second in minor units of cost_currency (evals, Story 7.6).",
    )
    cost_per_1k_tokens_minor: int = Field(
        default=0,
        ge=0,
        description="Cost of 1,000 tokens (input + output) in minor units of cost_currency.",
    )
    cost_currency: str = Field(
        default="EUR",
        pattern=r"^[A-Z]{3}$",
        description="ISO-4217 currency of the cost rates.",
    )
    log_level: Annotated[
        Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], BeforeValidator(str.upper)
    ] = "INFO"

    @model_validator(mode="after")
    def _download_key_set_in_prod(self) -> "Settings":
        if self.env == "prod" and self.download_signing_key == DEFAULT_DOWNLOAD_SIGNING_KEY:
            raise ValueError("download_signing_key must be set to a secret value when env is prod")
        return self

    @model_validator(mode="after")
    def _heartbeat_inside_lease(self) -> "Settings":
        if self.job_heartbeat_s > self.job_lease_s / 2:
            raise ValueError("job_heartbeat_s must be at most half of job_lease_s")
        return self

    @field_validator("alert_email_to", mode="before")
    @classmethod
    def _comma_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("openai_model", "openai_reasoning_effort", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # An empty value in `.env` (`PSA_OPENAI_MODEL=`) means "use the profile's own".
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _known_model_profile(self) -> "Settings":
        # Fails at startup rather than on the first model call.
        if self.model_profile_chat not in MODEL_PROFILES:
            known = ", ".join(sorted(MODEL_PROFILES))
            raise ValueError(
                f"model_profile_chat {self.model_profile_chat!r} is not a known profile ({known})"
            )
        if self.model_profile_embed not in EMBED_PROFILES:
            known = ", ".join(sorted(EMBED_PROFILES))
            raise ValueError(
                f"model_profile_embed {self.model_profile_embed!r} is not a known embedding "
                f"profile ({known})"
            )
        return self

    @model_validator(mode="after")
    def _overlap_inside_chunk(self) -> "Settings":
        if self.knowledge_chunk_overlap_chars * 2 >= self.knowledge_chunk_chars:
            raise ValueError(
                "knowledge_chunk_overlap_chars must be less than half of knowledge_chunk_chars"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
