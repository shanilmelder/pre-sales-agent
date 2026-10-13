"""Evaluation results (Story 7.6).

- `registry_eval_results`: one row per `make eval` run that finished in time. It holds the
  config version ids, model digests and prompt versions per Agent, the reference-set
  version (the first 12 hex characters of the sha256 of `evals/reference/`), the scores
  (JSONB: overall and per Agent), the bars (JSONB: metric, threshold, value, status
  `pass | fail | not_measured`, delta), the number of Opportunities and of draft
  annotations, the pending Evidence pairs, stage failures (slug, stage, code), tokens, GPU
  seconds, cost (integer minor units + ISO-4217 currency), `passed`, `accepted` (only a
  passed row is accepted), created by (an actor id) and at. `psa_app`: SELECT, INSERT only.

Revision ID: 0027_registry_eval_results
Revises: 0026_registry
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_registry_eval_results"
down_revision: str | None = "0026_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "registry_eval_results"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference_set_version", sa.Text(), nullable=False),
        sa.Column("config_version_ids", postgresql.JSONB(), nullable=False),
        sa.Column("model_digests", postgresql.JSONB(), nullable=False),
        sa.Column("prompt_versions", postgresql.JSONB(), nullable=False),
        sa.Column("scores", postgresql.JSONB(), nullable=False),
        sa.Column("bars", postgresql.JSONB(), nullable=False),
        sa.Column("failures", postgresql.JSONB(), nullable=False),
        sa.Column("opportunity_count", sa.Integer(), nullable=False),
        sa.Column("draft_count", sa.Integer(), nullable=False),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("gpu_seconds", sa.Float(), nullable=False),
        sa.Column("cost_minor", sa.BigInteger(), nullable=False),
        sa.Column("cost_currency", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "reference_set_version ~ '^[0-9a-f]{12}$'",
            name="ck_registry_eval_results_reference_set_version",
        ),
        sa.CheckConstraint(
            "opportunity_count >= 0 AND draft_count >= 0 AND pending_count >= 0 "
            "AND tokens >= 0 AND gpu_seconds >= 0 AND cost_minor >= 0",
            name="ck_registry_eval_results_counts",
        ),
        sa.CheckConstraint(
            "cost_currency ~ '^[A-Z]{3}$'", name="ck_registry_eval_results_cost_currency"
        ),
        sa.CheckConstraint("passed OR NOT accepted", name="ck_registry_eval_results_accepted"),
        sa.PrimaryKeyConstraint("id", name="pk_registry_eval_results"),
    )
    op.create_index(
        "ix_registry_eval_results_accepted_created_at", TABLE, ["accepted", "created_at"]
    )
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {TABLE} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_registry_eval_results_accepted_created_at", table_name=TABLE)
    op.drop_table(TABLE)
