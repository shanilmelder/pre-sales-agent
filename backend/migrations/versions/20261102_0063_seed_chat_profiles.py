"""Seed the three chat profiles that used to be built into the code.

`ollama-cloud-chat`, `openai-chat` and `anthropic-opus-chat` become `verified` rows of
`registry_model_profiles`, so every chat profile lives in the registry and the Admin list shows
them all. Their models are already approved (`0061`, `0062`). Ids are deterministic:
`uuid5(SEED_NAMESPACE, "model-profile/<name>")`; `created_by` is null. A name that already exists
keeps its row. The seed is a literal: this migration never imports the app.

Config versions pinned to these names (every dev version pins `ollama-cloud-chat`) resolve
through the new rows; no config version changes.

A downgrade deletes the seeded ids only (a pre-existing row of the same name has another id and
stays): a config version pinned to a seeded profile then fails as an unknown profile, as after
`0061`'s downgrade.

Revision ID: 0063_seed_chat_profiles
Revises: 0062_anthropic_custom_profiles
Create Date: 2026-11-02
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "0063_seed_chat_profiles"
down_revision: str | None = "0062_anthropic_custom_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILES = "registry_model_profiles"
SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE`."""
NUM_CTX = 32768
# (name, provider, model, temperature, reasoning_effort)
SEED_PROFILES: tuple[tuple[str, str, str, float | None, str | None], ...] = (
    ("ollama-cloud-chat", "ollama", "gpt-oss:120b-cloud", 0.1, None),
    ("openai-chat", "openai", "gpt-4.1-mini", 0.1, None),
    ("anthropic-opus-chat", "anthropic", "claude-opus-5-5", None, "medium"),
)


def _seed_id(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"model-profile/{name}")


def upgrade() -> None:
    profiles = sa.table(
        PROFILES,
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.Text()),
        sa.column("provider", sa.Text()),
        sa.column("model", sa.Text()),
        sa.column("num_ctx", sa.Integer()),
        sa.column("temperature", sa.Float()),
        sa.column("reasoning_effort", sa.Text()),
        sa.column("state", sa.Text()),
        sa.column("created_by", sa.Uuid()),
    )
    rows = [
        {
            "id": _seed_id(name),
            "name": name,
            "provider": provider,
            "model": model,
            "num_ctx": NUM_CTX,
            "temperature": temperature,
            "reasoning_effort": effort,
            "state": "verified",
            "created_by": None,
        }
        for name, provider, model, temperature, effort in SEED_PROFILES
    ]
    op.execute(insert(profiles).values(rows).on_conflict_do_nothing(index_elements=["name"]))


def downgrade() -> None:
    profiles = sa.table(PROFILES, sa.column("id", sa.Uuid()))
    seeded = [_seed_id(name) for name, *_ in SEED_PROFILES]
    op.execute(sa.delete(profiles).where(profiles.c.id.in_(seeded)))
