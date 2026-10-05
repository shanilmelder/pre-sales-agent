"""Specialist assessment runs, their tasks, and the Assessments with their Findings and
effort (Epic 5 slice 5A).

- `assessments_runs`: one row per assessment run (`queued`, `running`, `succeeded`,
  `partially_failed`, `failed`), with `queued_at` (last queued; staleness counts from
  there). `psa_app`: SELECT, INSERT, UPDATE of `status`, `queued_at`, `finished_at` only.
- `assessments_tasks`: one task per agent and run (`engineering_agent`, `pm_agent`,
  `security_agent`; `queued`, `running`, `succeeded`, `failed` with an `error_code`).
  `psa_app`: SELECT, INSERT, UPDATE of `status`, `error_code`, `started_at`, `finished_at`
  only.
- `assessments_assessments`: an agent's Assessments of an Opportunity, `current` or
  `superseded`, numbered per Opportunity and agent, with the recommendation, confidence,
  its basis and the count of dropped Findings and effort rows. At most one `current` per
  Opportunity and agent. `psa_app`: SELECT, INSERT, UPDATE of `status` only (superseding).
- `assessments_assessment_findings`: an Assessment's Findings (kind, severity, title,
  detail). `psa_app`: SELECT, INSERT only.
- `assessments_assessment_finding_requirements`: which Requirement versions a Finding cites
  (no foreign key to intake's table, AD-2). `psa_app`: SELECT, INSERT only.
- `assessments_effort`: an Assessment's effort per Requirement version, `numeric(10,1)`
  person-hours between 0.5 and 2,000. `psa_app`: SELECT, INSERT only.

No DELETE for `psa_app` on any of them (the 0002 default privileges are revoked).

Revision ID: 0017_assessments_specialists
Revises: 0016_gaps_question_approval
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_assessments_specialists"
down_revision: str | None = "0016_gaps_question_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "assessments.run_assessment"
AGENTS = "('engineering_agent', 'pm_agent', 'security_agent')"
ERROR_CODES = "('model_unavailable', 'model_timeout', 'output_invalid')"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "assessments_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partially_failed', 'failed')",
            name="ck_assessments_runs_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_runs"),
    )
    op.create_index(
        "ix_assessments_runs_opportunity_id_created_at",
        "assessments_runs",
        ["opportunity_id", "created_at"],
    )

    op.create_table(
        "assessments_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"agent IN {AGENTS}", name="ck_assessments_tasks_agent"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_assessments_tasks_status",
        ),
        sa.CheckConstraint(
            f"error_code IS NULL OR error_code IN {ERROR_CODES}",
            name="ck_assessments_tasks_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_assessments_tasks_failed_has_code",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["assessments_runs.id"],
            name="fk_assessments_tasks_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_tasks"),
        sa.UniqueConstraint("run_id", "agent", name="uq_assessments_tasks_run_id_agent"),
    )

    op.create_table(
        "assessments_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("confidence_basis", sa.Text(), nullable=False),
        sa.Column("dropped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(f"agent IN {AGENTS}", name="ck_assessments_assessments_agent"),
        sa.CheckConstraint(
            "status IN ('current', 'superseded')", name="ck_assessments_assessments_status"
        ),
        sa.CheckConstraint(
            "recommendation IN ('proceed', 'proceed_with_conditions', 'do_not_proceed')",
            name="ck_assessments_assessments_recommendation",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_assessments_assessments_confidence",
        ),
        sa.CheckConstraint("version >= 1", name="ck_assessments_assessments_version"),
        sa.CheckConstraint(
            "dropped_count >= 0", name="ck_assessments_assessments_dropped_count"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["assessments_runs.id"], name="fk_assessments_assessments_run_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_assessments"),
        sa.UniqueConstraint(
            "opportunity_id", "agent", "version", name="uq_assessments_assessments_version"
        ),
    )
    op.create_index(
        "uq_assessments_assessments_one_current",
        "assessments_assessments",
        ["opportunity_id", "agent"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "assessments_assessment_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('risk', 'constraint', 'dependency', 'opportunity')",
            name="ck_assessments_assessment_findings_kind",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_assessments_assessment_findings_severity",
        ),
        sa.CheckConstraint("position >= 1", name="ck_assessments_assessment_findings_position"),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments_assessments.id"],
            name="fk_assessments_assessment_findings_assessment_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_assessment_findings"),
        sa.UniqueConstraint(
            "assessment_id", "position", name="uq_assessments_assessment_findings_position"
        ),
    )

    op.create_table(
        "assessments_assessment_finding_requirements",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["assessments_assessment_findings.id"],
            name="fk_assessments_assessment_finding_reqs_finding_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "finding_id", "requirement_id", name="pk_assessments_assessment_finding_reqs"
        ),
    )

    op.create_table(
        "assessments_effort",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.Column("hours", sa.Numeric(10, 1), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.CheckConstraint("hours >= 0.5 AND hours <= 2000", name="ck_assessments_effort_hours"),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments_assessments.id"],
            name="fk_assessments_effort_assessment_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_effort"),
        sa.UniqueConstraint(
            "assessment_id", "requirement_id", name="uq_assessments_effort_requirement"
        ),
    )

    updatable = {
        "assessments_runs": "status, queued_at, finished_at",
        "assessments_tasks": "status, error_code, started_at, finished_at",
        "assessments_assessments": "status",
    }
    for table, columns in updatable.items():
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {APP_ROLE}")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"GRANT UPDATE ({columns}) ON {table} TO {APP_ROLE}")
    for table in (
        "assessments_assessment_findings",
        "assessments_assessment_finding_requirements",
        "assessments_effort",
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
    op.drop_table("assessments_effort")
    op.drop_table("assessments_assessment_finding_requirements")
    op.drop_table("assessments_assessment_findings")
    op.drop_index("uq_assessments_assessments_one_current", "assessments_assessments")
    op.drop_table("assessments_assessments")
    op.drop_table("assessments_tasks")
    op.drop_index("ix_assessments_runs_opportunity_id_created_at", "assessments_runs")
    op.drop_table("assessments_runs")
