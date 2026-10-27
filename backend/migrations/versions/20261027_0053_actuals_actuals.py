"""Actuals (Story 10.1; FR-49, FR-65).

- `actuals_actuals`: what delivery took for one Baseline Estimate line (`estimate_line_id`),
  or Unplanned work (no line), recorded against `estimate_version_id`. Each correction is a
  new row of the same `actual_group_id` with the next `version` and a `correction_reason`;
  only the newest is `is_current`. Effort and duration are `numeric(10,1)`, cost integer
  minor units with an ISO-4217 currency. Failed Assumptions are `[{assumption_id, version}]`.
  `psa_app` gets SELECT and INSERT, and UPDATE of `is_current` only: an Actual is never
  changed in place or deleted.
- `actuals_deliveries`: the Opportunity's **Close delivery** (one per Opportunity), which makes
  its derived status `delivered`. SELECT and INSERT only.

Estimate, catalogue and user ids carry no foreign key (AD-2); the Opportunity does.

Revision ID: 0053_actuals_actuals
Revises: 0052_estimates_baselines
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053_actuals_actuals"
down_revision: str | None = "0052_estimates_baselines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
ACTUALS = "actuals_actuals"
DELIVERIES = "actuals_deliveries"
CAUSES = (
    "('unknown_requirement', 'integration_complexity', 'customer_delay', 'scope_change', "
    "'estimation_error', 'other')"
)


def upgrade() -> None:
    op.create_table(
        ACTUALS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=False),
        sa.Column("estimate_line_id", sa.Uuid(), nullable=True),
        sa.Column("actual_group_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "integration_type_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("work_package_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("milestone_label", sa.Text(), nullable=True),
        sa.Column("effort_hours", sa.Numeric(10, 1), nullable=False),
        sa.Column("duration_days", sa.Numeric(10, 1), nullable=True),
        sa.Column("cost_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("variance_cause", sa.Text(), nullable=True),
        sa.Column(
            "failed_assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('milestone', 'final')", name="ck_actuals_actuals_kind"),
        sa.CheckConstraint(
            f"variance_cause IS NULL OR variance_cause IN {CAUSES}",
            name="ck_actuals_actuals_variance_cause",
        ),
        sa.CheckConstraint("version >= 1", name="ck_actuals_actuals_version"),
        sa.CheckConstraint(
            "effort_hours >= 0 AND (duration_days IS NULL OR duration_days >= 0)",
            name="ck_actuals_actuals_effort",
        ),
        sa.CheckConstraint(
            "(cost_minor IS NULL) = (currency IS NULL) AND (cost_minor IS NULL OR "
            "(cost_minor >= 0 AND currency ~ '^[A-Z]{3}$'))",
            name="ck_actuals_actuals_cost",
        ),
        sa.CheckConstraint(
            "(version = 1) = (correction_reason IS NULL)",
            name="ck_actuals_actuals_correction_has_reason",
        ),
        sa.CheckConstraint(
            "estimate_line_id IS NOT NULL OR variance_cause IN "
            "('scope_change', 'unknown_requirement', 'other')",
            name="ck_actuals_actuals_unplanned_cause",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities_opportunities.id"],
            name="fk_actuals_actuals_opportunity_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_actuals_actuals"),
        sa.UniqueConstraint(
            "actual_group_id", "version", name="uq_actuals_actuals_actual_group_id_version"
        ),
    )
    op.create_index("ix_actuals_actuals_opportunity_id", ACTUALS, ["opportunity_id"])
    op.create_index(
        "uq_actuals_actuals_current_group",
        ACTUALS,
        ["actual_group_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "uq_actuals_actuals_current_line",
        ACTUALS,
        ["estimate_line_id"],
        unique=True,
        postgresql_where=sa.text("is_current AND estimate_line_id IS NOT NULL"),
    )
    op.execute(f"GRANT SELECT, INSERT ON {ACTUALS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {ACTUALS} FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE (is_current) ON {ACTUALS} TO {APP_ROLE}")

    op.create_table(
        DELIVERIES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=False),
        sa.Column("closed_by", sa.Uuid(), nullable=False),
        sa.Column(
            "closed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities_opportunities.id"],
            name="fk_actuals_deliveries_opportunity_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_actuals_deliveries"),
        sa.UniqueConstraint("opportunity_id", name="uq_actuals_deliveries_opportunity_id"),
    )
    op.execute(f"GRANT SELECT, INSERT ON {DELIVERIES} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {DELIVERIES} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(DELIVERIES)
    op.drop_index("uq_actuals_actuals_current_line", ACTUALS)
    op.drop_index("uq_actuals_actuals_current_group", ACTUALS)
    op.drop_index("ix_actuals_actuals_opportunity_id", ACTUALS)
    op.drop_table(ACTUALS)
