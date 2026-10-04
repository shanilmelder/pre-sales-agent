"""Red Team Reviews, their Findings and runs (Story 6.5).

- `assessments_red_team_runs`: one row per `assessments.red_team_review` run (`queued`,
  `running`, `succeeded`, `failed` with an `error_code`). `psa_app`: SELECT, INSERT, UPDATE.
- `assessments_reviews`: Reviews (`kind` `red_team`), `current` or `superseded`, numbered per
  Opportunity and kind, with the Estimate Version reviewed (no foreign key to estimates'
  table, AD-2) and the count of dropped Findings. At most one `current` per Opportunity and
  kind. `psa_app`: SELECT, INSERT, UPDATE (superseding).
- `assessments_findings`: a Review's Findings (category, severity, title, argument).
  `psa_app`: SELECT, INSERT only.
- `assessments_finding_requirements`: which Requirement versions a Finding challenges (no
  foreign key to intake's table). `psa_app`: SELECT, INSERT only.
- `assessments_finding_lines`: which Estimate lines a Finding challenges (no foreign key to
  estimates' table). `psa_app`: SELECT, INSERT only.

No DELETE for `psa_app` on any of them (the 0002 default privileges are revoked).

Revision ID: 0014_assessments_red_team
Revises: 0013_estimates_assumptions
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_assessments_red_team"
down_revision: str | None = "0013_estimates_assumptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "assessments.red_team_review"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "assessments_red_team_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_assessments_red_team_runs_failed_has_code",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid')",
            name="ck_assessments_red_team_runs_error_code",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_assessments_red_team_runs_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_red_team_runs"),
    )
    op.create_index(
        "ix_assessments_red_team_runs_opportunity_id_created_at",
        "assessments_red_team_runs",
        ["opportunity_id", "created_at"],
    )

    op.create_table(
        "assessments_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("dropped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("kind IN ('red_team')", name="ck_assessments_reviews_kind"),
        sa.CheckConstraint(
            "status IN ('current', 'superseded')", name="ck_assessments_reviews_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_assessments_reviews_version"),
        sa.CheckConstraint("dropped_count >= 0", name="ck_assessments_reviews_dropped_count"),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_reviews"),
        sa.UniqueConstraint(
            "opportunity_id",
            "kind",
            "version",
            name="uq_assessments_reviews_opportunity_id_kind_version",
        ),
    )
    op.create_index(
        "uq_assessments_reviews_one_current",
        "assessments_reviews",
        ["opportunity_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "assessments_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("argument", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "category IN ('integration_harder', 'requirement_incomplete', "
            "'capability_overstated', 'hidden_dependency')",
            name="ck_assessments_findings_category",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_assessments_findings_severity",
        ),
        sa.CheckConstraint("position >= 1", name="ck_assessments_findings_position"),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["assessments_reviews.id"],
            name="fk_assessments_findings_review_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_findings"),
        sa.UniqueConstraint(
            "review_id", "position", name="uq_assessments_findings_review_id_position"
        ),
    )

    op.create_table(
        "assessments_finding_requirements",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["assessments_findings.id"],
            name="fk_assessments_finding_requirements_finding_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "finding_id", "requirement_id", name="pk_assessments_finding_requirements"
        ),
    )

    op.create_table(
        "assessments_finding_lines",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["assessments_findings.id"],
            name="fk_assessments_finding_lines_finding_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("finding_id", "line_id", name="pk_assessments_finding_lines"),
    )

    for table in ("assessments_red_team_runs", "assessments_reviews"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE DELETE ON {table} FROM {APP_ROLE}")
    for table in (
        "assessments_findings",
        "assessments_finding_requirements",
        "assessments_finding_lines",
    ):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    # Jobs for a type the older code doesn't have would only go dead.
    op.execute(
        "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        "lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_table("assessments_finding_lines")
    op.drop_table("assessments_finding_requirements")
    op.drop_table("assessments_findings")
    op.drop_index("uq_assessments_reviews_one_current", "assessments_reviews")
    op.drop_table("assessments_reviews")
    op.drop_index("ix_assessments_red_team_runs_opportunity_id_created_at", "assessments_red_team_runs")
    op.drop_table("assessments_red_team_runs")
