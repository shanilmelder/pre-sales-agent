"""The Postgres job queue table (AD-29, Story 2.2 Part A).

`platform_jobs` holds one row per job. `priority` is the class rank (0 = interactive,
1 = background). The partial index `ix_platform_jobs_claim` covers only rows a claim can
still pick up. Jobs are never deleted by the app: `psa_app` keeps SELECT, INSERT and UPDATE
from the default privileges (0002) and loses DELETE here.

Revision ID: 0006_platform_jobs
Revises: 0005_intake_sources
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_platform_jobs"
down_revision: str | None = "0005_intake_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"


def upgrade() -> None:
    op.create_table(
        "platform_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed_retrying', 'dead')",
            name="ck_platform_jobs_status",
        ),
        sa.CheckConstraint("priority IN (0, 1)", name="ck_platform_jobs_priority"),
        sa.CheckConstraint("attempts >= 0", name="ck_platform_jobs_attempts"),
        sa.PrimaryKeyConstraint("id", name="pk_platform_jobs"),
    )
    op.create_index(
        "ix_platform_jobs_claim",
        "platform_jobs",
        ["priority", "run_after", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'failed_retrying', 'running')"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform_jobs TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON platform_jobs FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_platform_jobs_claim", table_name="platform_jobs")
    op.drop_table("platform_jobs")
