"""Gaps and their Clarification Questions (Story 4.3).

- `gaps_detections`: one row per `gaps.detect_gaps` run (`queued`, `running`, `succeeded`,
  `failed` with an `error_code`) and its counts. `psa_app`: SELECT, INSERT, UPDATE.
- `gaps_gaps`: Gaps with their category, trigger (jsonb), why it matters, impact and basis,
  origin and status (`row_version` for optimistic concurrency). `psa_app`: SELECT, INSERT,
  UPDATE.
- `gaps_gap_requirements`: which Requirement versions a Gap relates to (no foreign key to
  intake's table, AD-2). `psa_app`: SELECT, INSERT only.
- `gaps_clarification_questions`: one drafted question per Gap. `psa_app`: SELECT, INSERT,
  UPDATE.

No DELETE for `psa_app` on any of them (the 0002 default privileges are revoked).

Revision ID: 0011_gaps
Revises: 0010_intake_requirement_edits
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_gaps"
down_revision: str | None = "0010_intake_requirement_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "gaps.detect_gaps"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "gaps_detections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("gap_count", sa.Integer(), nullable=True),
        sa.Column("dropped_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_gaps_detections_failed_has_code",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid')",
            name="ck_gaps_detections_error_code",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_gaps_detections_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gaps_detections"),
    )
    op.create_index(
        "ix_gaps_detections_opportunity_id_created_at",
        "gaps_detections",
        ["opportunity_id", "created_at"],
    )

    op.create_table(
        "gaps_gaps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("trigger", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("impact_basis", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detection_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "category IN ('data_volumes', 'versions_and_platforms', 'integration_details', "
            "'security_and_compliance', 'non_functional', 'scope_and_ownership', "
            "'commercial', 'other')",
            name="ck_gaps_gaps_category",
        ),
        sa.CheckConstraint("impact IN ('high', 'medium', 'low')", name="ck_gaps_gaps_impact"),
        sa.CheckConstraint("origin IN ('detected')", name="ck_gaps_gaps_origin"),
        sa.CheckConstraint("status IN ('open', 'superseded')", name="ck_gaps_gaps_status"),
        sa.ForeignKeyConstraint(
            ["detection_id"],
            ["gaps_detections.id"],
            name="fk_gaps_gaps_detection_id_gaps_detections",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gaps_gaps"),
    )
    op.create_index(
        "ix_gaps_gaps_opportunity_id_status", "gaps_gaps", ["opportunity_id", "status"]
    )

    op.create_table(
        "gaps_clarification_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gap_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "status_changed_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('drafted', 'superseded')", name="ck_gaps_clarification_questions_status"
        ),
        sa.ForeignKeyConstraint(
            ["gap_id"],
            ["gaps_gaps.id"],
            name="fk_gaps_clarification_questions_gap_id_gaps_gaps",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gaps_clarification_questions"),
        sa.UniqueConstraint("gap_id", name="uq_gaps_clarification_questions_gap_id"),
    )

    op.create_table(
        "gaps_gap_requirements",
        sa.Column("gap_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gap_id"],
            ["gaps_gaps.id"],
            name="fk_gaps_gap_requirements_gap_id_gaps_gaps",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("gap_id", "requirement_id", name="pk_gaps_gap_requirements"),
    )

    for table in ("gaps_detections", "gaps_gaps", "gaps_clarification_questions"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE DELETE ON {table} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON gaps_gap_requirements TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON gaps_gap_requirements FROM {APP_ROLE}")


def downgrade() -> None:
    # Jobs for a type the older code doesn't have would only go dead.
    op.execute(
        "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        "lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_table("gaps_gap_requirements")
    op.drop_table("gaps_clarification_questions")
    op.drop_index("ix_gaps_gaps_opportunity_id_status", "gaps_gaps")
    op.drop_table("gaps_gaps")
    op.drop_index("ix_gaps_detections_opportunity_id_created_at", "gaps_detections")
    op.drop_table("gaps_detections")
