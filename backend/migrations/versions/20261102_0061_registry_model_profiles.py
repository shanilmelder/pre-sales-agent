"""Admin-managed chat model profiles and the approved-model allowlist.

- `registry_model_profiles`: custom chat profiles (`name` unique; provider, model, `num_ctx`,
  and either `temperature` or `reasoning_effort`). The definition is immutable. `psa_app`:
  SELECT, INSERT and UPDATE of `state`, `error_code`, `latency_ms` and `tested_at` only (no
  DELETE). No base URL, API key or other secret: those stay in the environment.
- `registry_approved_models`: the provider and model pairs a custom profile may name. `psa_app`:
  SELECT, INSERT, DELETE (no UPDATE). Seeded with the two built-in models, with deterministic
  ids: `uuid5(SEED_NAMESPACE, "approved-model/<provider>/<model>")`. The seed is a literal: this
  migration never imports the app.

A downgrade drops custom profiles: a config version pinned to one then fails as an unknown
profile.

Revision ID: 0061_registry_model_profiles
Revises: 0060_chat_profile_rename
Create Date: 2026-11-02
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061_registry_model_profiles"
down_revision: str | None = "0060_chat_profile_rename"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
PROFILES = "registry_model_profiles"
APPROVED = "registry_approved_models"
SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE`."""
SEED_MODELS: tuple[tuple[str, str], ...] = (
    ("ollama", "gpt-oss:120b-cloud"),
    ("openai", "gpt-4.1-mini"),
)


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        PROFILES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("num_ctx", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("reasoning_effort", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "name ~ '^[a-z0-9][a-z0-9._-]*$' AND char_length(name) <= 64",
            name=f"ck_{PROFILES}_name",
        ),
        sa.CheckConstraint("provider IN ('ollama', 'openai')", name=f"ck_{PROFILES}_provider"),
        sa.CheckConstraint("char_length(model) BETWEEN 1 AND 128", name=f"ck_{PROFILES}_model"),
        sa.CheckConstraint("num_ctx BETWEEN 16384 AND 2097152", name=f"ck_{PROFILES}_num_ctx"),
        sa.CheckConstraint(
            "(temperature IS NULL) <> (reasoning_effort IS NULL)",
            name=f"ck_{PROFILES}_temperature_or_effort",
        ),
        sa.CheckConstraint(
            "temperature IS NULL OR temperature BETWEEN 0 AND 2",
            name=f"ck_{PROFILES}_temperature",
        ),
        sa.CheckConstraint(
            "reasoning_effort IS NULL OR (provider = 'openai' "
            "AND reasoning_effort IN ('low', 'medium', 'high'))",
            name=f"ck_{PROFILES}_reasoning_effort",
        ),
        sa.CheckConstraint(
            "state IN ('untested', 'verified', 'failed', 'retired')", name=f"ck_{PROFILES}_state"
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name=f"ck_{PROFILES}_latency_ms"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PROFILES}"),
        sa.UniqueConstraint("name", name=f"uq_{PROFILES}_name"),
    )
    op.create_table(
        APPROVED,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("provider IN ('ollama', 'openai')", name=f"ck_{APPROVED}_provider"),
        sa.CheckConstraint("char_length(model) BETWEEN 1 AND 128", name=f"ck_{APPROVED}_model"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{APPROVED}"),
        sa.UniqueConstraint("provider", "model", name=f"uq_{APPROVED}_provider_model"),
    )
    op.execute(f"REVOKE ALL ON {PROFILES} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {PROFILES} TO {APP_ROLE}")
    op.execute(
        f"GRANT UPDATE (state, error_code, latency_ms, tested_at) ON {PROFILES} TO {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON {APPROVED} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {APPROVED} TO {APP_ROLE}")

    approved = sa.table(
        APPROVED,
        sa.column("id", sa.Uuid()),
        sa.column("provider", sa.Text()),
        sa.column("model", sa.Text()),
    )
    op.bulk_insert(
        approved,
        [
            {
                "id": uuid.uuid5(SEED_NAMESPACE, f"approved-model/{provider}/{model}"),
                "provider": provider,
                "model": model,
            }
            for provider, model in SEED_MODELS
        ],
    )


def downgrade() -> None:
    op.drop_table(APPROVED)
    op.drop_table(PROFILES)
