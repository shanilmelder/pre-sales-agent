"""One row per ModelGateway call (AD-8, Story 2.4).

`platform_model_calls` records who called (agent, config version, run, task, Opportunity),
the profile, model and digest, the priority, token counts, latency, attempts and the outcome.
It never holds prompt or response text. Rows are written once and never changed: `psa_app`
gets SELECT and INSERT only (UPDATE and DELETE from the 0002 default privileges are revoked).

Revision ID: 0007_platform_model_calls
Revises: 0006_platform_jobs
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_platform_model_calls"
down_revision: str | None = "0006_platform_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"


def upgrade() -> None:
    op.create_table(
        "platform_model_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("config_version", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_digest", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'invalid_output', 'error', 'timeout')",
            name="ck_platform_model_calls_outcome",
        ),
        sa.CheckConstraint(
            "priority IN ('interactive', 'background')",
            name="ck_platform_model_calls_priority",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0 AND attempts >= 0",
            name="ck_platform_model_calls_counts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_model_calls"),
    )
    op.create_index("ix_platform_model_calls_run_id", "platform_model_calls", ["run_id"])
    op.create_index(
        "ix_platform_model_calls_opportunity_id_created_at",
        "platform_model_calls",
        ["opportunity_id", "created_at"],
    )
    op.execute(f"GRANT SELECT, INSERT ON platform_model_calls TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON platform_model_calls FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(
        "ix_platform_model_calls_opportunity_id_created_at", table_name="platform_model_calls"
    )
    op.drop_index("ix_platform_model_calls_run_id", table_name="platform_model_calls")
    op.drop_table("platform_model_calls")
