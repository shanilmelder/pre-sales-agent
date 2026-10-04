"""Estimate Versions, their lines and drafts (Story 8.1).

- `estimates_drafts`: one row per `estimates.draft_estimate` run (`queued`, `running`,
  `succeeded`, `failed` with an `error_code`). `psa_app`: SELECT, INSERT, UPDATE.
- `estimates_estimate_versions`: Estimate Versions (`draft` or `superseded`) with their
  template version and counts (`row_version` for optimistic concurrency). At most one `draft`
  per Opportunity. `psa_app`: SELECT, INSERT, UPDATE.
- `estimates_estimate_lines`: a version's work items with effort (`numeric(10,1)` hours),
  role mix (jsonb) and basis. No totals are stored: they are calculated on read.
  `psa_app`: SELECT, INSERT only (no inline editing in the demo).
- `estimates_line_requirements`: which Requirement versions a line covers (no foreign key to
  intake's table, AD-2). `psa_app`: SELECT, INSERT only.

No DELETE for `psa_app` on any of them (the 0002 default privileges are revoked).

Revision ID: 0012_estimates
Revises: 0011_gaps
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_estimates"
down_revision: str | None = "0011_gaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "estimates.draft_estimate"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "estimates_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_estimates_drafts_failed_has_code",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid')",
            name="ck_estimates_drafts_error_code",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_estimates_drafts_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimates_drafts"),
    )
    op.create_index(
        "ix_estimates_drafts_opportunity_id_created_at",
        "estimates_drafts",
        ["opportunity_id", "created_at"],
    )

    op.create_table(
        "estimates_estimate_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("uncovered_count", sa.Integer(), nullable=False),
        sa.Column("dropped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'superseded')", name="ck_estimates_estimate_versions_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_estimates_estimate_versions_version"),
        sa.CheckConstraint(
            "uncovered_count >= 0 AND dropped_count >= 0",
            name="ck_estimates_estimate_versions_counts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimates_estimate_versions"),
        sa.UniqueConstraint(
            "opportunity_id",
            "version",
            name="uq_estimates_estimate_versions_opportunity_id_version",
        ),
    )
    op.create_index(
        "uq_estimates_estimate_versions_one_draft",
        "estimates_estimate_versions",
        ["opportunity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )

    op.create_table(
        "estimates_estimate_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("effort_hours", sa.Numeric(10, 1), nullable=False),
        sa.Column("role_mix", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "section IN ('functional', 'integration', 'data', 'security', 'non_functional', "
            "'commercial')",
            name="ck_estimates_estimate_lines_section",
        ),
        sa.CheckConstraint("effort_hours >= 0", name="ck_estimates_estimate_lines_effort_hours"),
        sa.CheckConstraint("position >= 1", name="ck_estimates_estimate_lines_position"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["estimates_estimate_versions.id"],
            name="fk_estimates_estimate_lines_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimates_estimate_lines"),
        sa.UniqueConstraint(
            "version_id", "position", name="uq_estimates_estimate_lines_version_id_position"
        ),
    )

    op.create_table(
        "estimates_line_requirements",
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["estimates_estimate_lines.id"],
            name="fk_estimates_line_requirements_line_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "line_id", "requirement_id", name="pk_estimates_line_requirements"
        ),
    )

    for table in ("estimates_drafts", "estimates_estimate_versions"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE DELETE ON {table} FROM {APP_ROLE}")
    for table in ("estimates_estimate_lines", "estimates_line_requirements"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    # Jobs for a type the older code doesn't have would only go dead.
    op.execute(
        "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        "lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_table("estimates_line_requirements")
    op.drop_table("estimates_estimate_lines")
    op.drop_index("uq_estimates_estimate_versions_one_draft", "estimates_estimate_versions")
    op.drop_table("estimates_estimate_versions")
    op.drop_index("ix_estimates_drafts_opportunity_id_created_at", "estimates_drafts")
    op.drop_table("estimates_drafts")
