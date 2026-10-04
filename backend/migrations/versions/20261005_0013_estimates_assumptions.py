"""Assumptions and converted Gaps (Story 8.4).

- `estimates_assumptions`: an Estimate Version's Assumptions, each a `condition` (no hours) or
  a `contingency` (`numeric(10,1)` hours, optionally linked to a line), with its origin
  (`origin_ref` jsonb: `{kind: "gap", id, row_version}`, no foreign key to gaps' table,
  AD-2), and who accepted it and when (null until accepted). `row_version` for optimistic
  concurrency. `psa_app`: SELECT, INSERT, UPDATE (no DELETE).
- `estimates_estimate_versions.proposal_status`: the state of the version's Assumption
  proposals (`queued`, `running`, `succeeded`, `failed`; null when none were queued).
- `gaps_gaps`: the status check allows `converted`, and `converted_to` records the kind of
  Assumption it became (`condition` or `contingency`), set exactly when `converted`.

Revision ID: 0013_estimates_assumptions
Revises: 0012_estimates
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_estimates_assumptions"
down_revision: str | None = "0012_estimates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "estimates.propose_assumptions"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.add_column("gaps_gaps", sa.Column("converted_to", sa.Text(), nullable=True))
    op.drop_constraint("ck_gaps_gaps_status", "gaps_gaps", type_="check")
    op.create_check_constraint(
        "ck_gaps_gaps_status", "gaps_gaps", "status IN ('open', 'superseded', 'converted')"
    )
    op.create_check_constraint(
        "ck_gaps_gaps_converted_to",
        "gaps_gaps",
        "converted_to IS NULL OR converted_to IN ('condition', 'contingency')",
    )
    op.create_check_constraint(
        "ck_gaps_gaps_converted_has_kind",
        "gaps_gaps",
        "(status = 'converted') = (converted_to IS NOT NULL)",
    )

    op.add_column(
        "estimates_estimate_versions",
        sa.Column("proposal_status", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_estimates_estimate_versions_proposal_status",
        "estimates_estimate_versions",
        "proposal_status IS NULL OR proposal_status IN "
        "('queued', 'running', 'succeeded', 'failed')",
    )

    op.create_table(
        "estimates_assumptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("wording", sa.Text(), nullable=False),
        sa.Column("amount_hours", sa.Numeric(10, 1), nullable=True),
        sa.Column("line_id", sa.Uuid(), nullable=True),
        sa.Column("origin_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('condition', 'contingency')", name="ck_estimates_assumptions_kind"),
        sa.CheckConstraint(
            "(kind = 'contingency') = (amount_hours IS NOT NULL)",
            name="ck_estimates_assumptions_contingency_has_hours",
        ),
        sa.CheckConstraint(
            "amount_hours IS NULL OR amount_hours > 0",
            name="ck_estimates_assumptions_amount_hours",
        ),
        sa.CheckConstraint(
            "kind = 'contingency' OR line_id IS NULL",
            name="ck_estimates_assumptions_condition_has_no_line",
        ),
        sa.CheckConstraint(
            "(accepted_by IS NULL) = (accepted_at IS NULL)",
            name="ck_estimates_assumptions_accepted_has_by",
        ),
        sa.CheckConstraint("position >= 1", name="ck_estimates_assumptions_position"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["estimates_estimate_versions.id"],
            name="fk_estimates_assumptions_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["estimates_estimate_lines.id"],
            name="fk_estimates_assumptions_line_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimates_assumptions"),
        sa.UniqueConstraint(
            "version_id", "position", name="uq_estimates_assumptions_version_id_position"
        ),
    )
    op.create_index(
        "ix_estimates_assumptions_version_id", "estimates_assumptions", ["version_id"]
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON estimates_assumptions TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON estimates_assumptions FROM {APP_ROLE}")


def downgrade() -> None:
    # Jobs for a type the older code doesn't have would only go dead.
    op.execute(
        "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        "lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_index("ix_estimates_assumptions_version_id", "estimates_assumptions")
    op.drop_table("estimates_assumptions")
    op.drop_constraint(
        "ck_estimates_estimate_versions_proposal_status",
        "estimates_estimate_versions",
        type_="check",
    )
    op.drop_column("estimates_estimate_versions", "proposal_status")
    # Converted Gaps go back to open: the older code has no `converted`.
    op.drop_constraint("ck_gaps_gaps_converted_has_kind", "gaps_gaps", type_="check")
    op.drop_constraint("ck_gaps_gaps_converted_to", "gaps_gaps", type_="check")
    op.execute("UPDATE gaps_gaps SET status = 'open' WHERE status = 'converted'")
    op.drop_constraint("ck_gaps_gaps_status", "gaps_gaps", type_="check")
    op.create_check_constraint(
        "ck_gaps_gaps_status", "gaps_gaps", "status IN ('open', 'superseded')"
    )
    op.drop_column("gaps_gaps", "converted_to")
