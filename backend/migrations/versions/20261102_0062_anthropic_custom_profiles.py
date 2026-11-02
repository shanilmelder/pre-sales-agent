"""`anthropic` as a custom model profile provider.

Widens `registry_model_profiles` and `registry_approved_models` to provider `anthropic`, lets an
`anthropic` profile store a `reasoning_effort`, and seeds the two approved Claude models, with
the deterministic ids of `0061`: `uuid5(SEED_NAMESPACE, "approved-model/<provider>/<model>")`.
The seed is a literal: this migration never imports the app.

Constraint names are the ones `0061` passed. `env.py`'s naming convention rewrites each of them,
doubling the prefix and hashing the two that pass 63 characters (the provider check on
`registry_approved_models` and `reasoning_effort`), and it rewrites the same input the same way
when dropping and creating. So those literals reach the real constraints, and the rewritten
constraints keep their real names.

A downgrade deletes every `anthropic` profile and approved model, which the old constraints
can't hold: a config version pinned to such a profile then fails as an unknown profile.

Revision ID: 0062_anthropic_custom_profiles
Revises: 0061_registry_model_profiles
Create Date: 2026-11-02
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062_anthropic_custom_profiles"
down_revision: str | None = "0061_registry_model_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILES = "registry_model_profiles"
APPROVED = "registry_approved_models"
SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE`."""
SEED_MODELS: tuple[tuple[str, str], ...] = (
    ("anthropic", "claude-opus-5-5"),
    ("anthropic", "claude-sonnet-5-5"),
)
EFFORTS = "reasoning_effort IN ('low', 'medium', 'high')"
OLD_PROVIDERS = "provider IN ('ollama', 'openai')"
NEW_PROVIDERS = "provider IN ('ollama', 'openai', 'anthropic')"
OLD_EFFORT = f"reasoning_effort IS NULL OR (provider = 'openai' AND {EFFORTS})"
NEW_EFFORT = f"reasoning_effort IS NULL OR (provider IN ('openai', 'anthropic') AND {EFFORTS})"


def _set_constraints(providers: str, effort: str) -> None:
    for table, name, condition in (
        (PROFILES, f"ck_{PROFILES}_provider", providers),
        (PROFILES, f"ck_{PROFILES}_reasoning_effort", effort),
        (APPROVED, f"ck_{APPROVED}_provider", providers),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    _set_constraints(NEW_PROVIDERS, NEW_EFFORT)
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
    op.execute(f"DELETE FROM {PROFILES} WHERE provider = 'anthropic'")
    op.execute(f"DELETE FROM {APPROVED} WHERE provider = 'anthropic'")
    _set_constraints(OLD_PROVIDERS, OLD_EFFORT)
