"""Conflicts between the specialist Assessments, and their positions (Story 6.1).

- `conflicts_conflicts`: one row per Conflict raised for an Opportunity by an assessment run
  (`run_id`, an assessments id; no foreign key across modules, AD-2) in a detection pass
  (`detection_pass`: 1, then 2, … each time the run finishes again after a task retry),
  unique per run, pass and `fingerprint`: its `type` (timeline, effort, resource, architecture, security, scope,
  assumption, evidence), `severity`, `status` (`open`, `negotiating`, `resolved`,
  `escalated`), `detected_by` (`rule`, `semantic`, `critic`, `red_team`), a summary, the
  Conflict of an earlier run it carries forward (`previous_conflict_id`), and when resolved
  the reason and time. `row_version` counts its changes. `psa_app`: SELECT, INSERT, and
  UPDATE of `status`, `resolution_reason`, `resolved_at` and `row_version` only.
- `conflicts_positions`: a Conflict's positions in order, each from an agent's Assessment
  (`assessment_id`, `assessment_version`, `agent`) or the Estimate (`estimate_version_id`,
  `estimate_version`), with a summary, an hours value (`numeric(10,1)`, or null) and the
  Requirement version it is about (or none). `psa_app`: SELECT, INSERT only.

No DELETE for `psa_app` on either (the 0002 default privileges are revoked).

Revision ID: 0021_conflicts
Revises: 0020_opportunities_imports
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_conflicts"
down_revision: str | None = "0020_opportunities_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TYPES = (
    "('timeline', 'effort', 'resource', 'architecture', 'security', 'scope', 'assumption', "
    "'evidence')"
)


def upgrade() -> None:
    op.create_table(
        "conflicts_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detected_by", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("previous_conflict_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detection_pass", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"type IN {TYPES}", name="ck_conflicts_conflicts_type"),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_conflicts_conflicts_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'negotiating', 'resolved', 'escalated')",
            name="ck_conflicts_conflicts_status",
        ),
        sa.CheckConstraint(
            "detected_by IN ('rule', 'semantic', 'critic', 'red_team')",
            name="ck_conflicts_conflicts_detected_by",
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)",
            name="ck_conflicts_conflicts_resolved_at",
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL) = (resolution_reason IS NULL)",
            name="ck_conflicts_conflicts_resolution_reason",
        ),
        sa.CheckConstraint("row_version >= 1", name="ck_conflicts_conflicts_row_version"),
        sa.CheckConstraint("detection_pass >= 1", name="ck_conflicts_conflicts_detection_pass"),
        sa.ForeignKeyConstraint(
            ["previous_conflict_id"],
            ["conflicts_conflicts.id"],
            name="fk_conflicts_conflicts_previous_conflict_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conflicts_conflicts"),
        sa.UniqueConstraint(
            "run_id",
            "detection_pass",
            "fingerprint",
            name="uq_conflicts_conflicts_run_id_detection_pass_fingerprint",
        ),
    )
    op.create_index(
        "ix_conflicts_conflicts_opportunity_id_created_at",
        "conflicts_conflicts",
        ["opportunity_id", "created_at"],
    )
    op.create_index(
        "ix_conflicts_conflicts_previous_conflict_id",
        "conflicts_conflicts",
        ["previous_conflict_id"],
    )

    op.create_table(
        "conflicts_positions",
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=True),
        sa.Column("assessment_version", sa.Integer(), nullable=True),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=True),
        sa.Column("estimate_version", sa.Integer(), nullable=True),
        sa.Column("agent", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(10, 1), nullable=True),
        sa.Column("requirement_id", sa.Uuid(), nullable=True),
        sa.Column("requirement_version", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "source IN ('assessment', 'estimate')", name="ck_conflicts_positions_source"
        ),
        sa.CheckConstraint(
            "(source = 'assessment') = (assessment_id IS NOT NULL AND assessment_version IS "
            "NOT NULL AND agent IS NOT NULL)",
            name="ck_conflicts_positions_assessment_ref",
        ),
        sa.CheckConstraint(
            "(source = 'estimate') = (estimate_version_id IS NOT NULL AND estimate_version IS "
            "NOT NULL)",
            name="ck_conflicts_positions_estimate_ref",
        ),
        sa.CheckConstraint(
            "source = 'assessment' OR agent IS NULL",
            name="ck_conflicts_positions_estimate_has_no_agent",
        ),
        sa.CheckConstraint(
            "(requirement_id IS NULL) = (requirement_version IS NULL)",
            name="ck_conflicts_positions_requirement_ref",
        ),
        sa.CheckConstraint("position >= 1", name="ck_conflicts_positions_position"),
        sa.ForeignKeyConstraint(
            ["conflict_id"],
            ["conflicts_conflicts.id"],
            name="fk_conflicts_positions_conflict_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("conflict_id", "position", name="pk_conflicts_positions"),
    )

    op.execute(f"REVOKE UPDATE, DELETE ON conflicts_conflicts FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON conflicts_conflicts TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (status, resolution_reason, resolved_at, row_version) "
        f"ON conflicts_conflicts TO {APP_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT ON conflicts_positions TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON conflicts_positions FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("conflicts_positions")
    op.drop_index("ix_conflicts_conflicts_previous_conflict_id", "conflicts_conflicts")
    op.drop_index("ix_conflicts_conflicts_opportunity_id_created_at", "conflicts_conflicts")
    op.drop_table("conflicts_conflicts")
