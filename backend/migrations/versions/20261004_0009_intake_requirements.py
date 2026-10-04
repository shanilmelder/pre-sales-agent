"""Extracted Requirements with cited Source passages (Story 2.5 Part A).

- `intake_extractions`: one row per `intake.extract_requirements` run (`queued`, `running`,
  `succeeded`, `failed` with an `error_code`) and its counts. `psa_app`: SELECT, INSERT,
  UPDATE.
- `intake_source_passages`: immutable code-point spans `[start, end)` of a Source version's
  extracted text, one row per span. `psa_app`: SELECT, INSERT only.
- `intake_requirements`: Requirements with their classification, origin, lock, status and
  version (`row_version` for optimistic concurrency). `psa_app`: SELECT, INSERT, UPDATE.
- `intake_requirement_evidence`: which passages a Requirement cites. `psa_app`: SELECT,
  INSERT only.

No DELETE for `psa_app` on any of them (the 0002 default privileges are revoked).

Revision ID: 0009_intake_requirements
Revises: 0008_platform_model_calls
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_intake_requirements"
down_revision: str | None = "0008_platform_model_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "intake.extract_requirements"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "intake_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("requirement_count", sa.Integer(), nullable=True),
        sa.Column("dropped_count", sa.Integer(), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_intake_extractions_failed_has_code",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid', 'input_too_large')",
            name="ck_intake_extractions_error_code",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_intake_extractions_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intake_extractions"),
    )
    op.create_index(
        "ix_intake_extractions_opportunity_id_created_at",
        "intake_extractions",
        ["opportunity_id", "created_at"],
    )

    op.create_table(
        "intake_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("locked_by_human", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "classification IN ('functional', 'integration', 'data', 'security', "
            "'non_functional', 'commercial')",
            name="ck_intake_requirements_classification",
        ),
        sa.CheckConstraint(
            "origin IN ('extracted', 'human')", name="ck_intake_requirements_origin"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_intake_requirements_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_intake_requirements_version"),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["intake_extractions.id"],
            name="fk_intake_requirements_extraction_id_intake_extractions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intake_requirements"),
    )
    op.create_index(
        "ix_intake_requirements_opportunity_id_status",
        "intake_requirements",
        ["opportunity_id", "status"],
    )

    op.create_table(
        "intake_source_passages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint('start >= 0 AND "end" > start', name="ck_intake_source_passages_span"),
        sa.ForeignKeyConstraint(
            ["source_id", "source_version"],
            ["intake_source_versions.source_id", "intake_source_versions.version"],
            name="fk_intake_source_passages_source_id_intake_source_versions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intake_source_passages"),
        sa.UniqueConstraint(
            "source_id",
            "source_version",
            "start",
            "end",
            name="uq_intake_source_passages_source_id_source_version_start_end",
        ),
    )

    op.create_table(
        "intake_requirement_evidence",
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("passage_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["passage_id"],
            ["intake_source_passages.id"],
            name="fk_intake_requirement_evidence_passage_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["intake_requirements.id"],
            name="fk_intake_requirement_evidence_requirement_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "requirement_id", "passage_id", name="pk_intake_requirement_evidence"
        ),
    )
    op.create_index(
        "ix_intake_requirement_evidence_passage_id",
        "intake_requirement_evidence",
        ["passage_id"],
    )

    for table in ("intake_extractions", "intake_requirements"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE DELETE ON {table} FROM {APP_ROLE}")
    for table in ("intake_source_passages", "intake_requirement_evidence"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    # Jobs for a type the older code doesn't have would only go dead.
    op.execute(
        "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        "lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_index("ix_intake_requirement_evidence_passage_id", "intake_requirement_evidence")
    op.drop_table("intake_requirement_evidence")
    op.drop_table("intake_source_passages")
    op.drop_index("ix_intake_requirements_opportunity_id_status", "intake_requirements")
    op.drop_table("intake_requirements")
    op.drop_index("ix_intake_extractions_opportunity_id_created_at", "intake_extractions")
    op.drop_table("intake_extractions")
