"""Risks, and editing Assumptions (Story 8.5).

- `estimates_risks`: an Estimate Version's Risks, each made from one Gap (`origin_ref` jsonb:
  `{kind: "gap", id, row_version}`, no foreign key to gaps' table, AD-2): a description
  (1-500 characters), a `likelihood` and an `impact` (`low|medium|high`), who created it and
  when, who changed it last (`changed_by`), `carried_from` (the Risk of the superseded draft a
  re-draft copied it from, ON DELETE SET NULL) and `row_version`; unique per (version,
  position). `psa_app`: SELECT, INSERT, UPDATE (no DELETE).
- `estimates_assumptions.changed_by`: the person behind the Assumption's latest change (an
  accept or an edit), named in a 412; null until a person changes it. `psa_app` may now
  DELETE Assumptions: converting a Gap to a Risk removes the draft's unaccepted Assumption
  proposed for the same Gap.
- `gaps_gaps.converted_to` also allows `risk`.

Downgrade: Gaps converted to a Risk go back to `open`, and the table, column and grant are
dropped.

Revision ID: 0042_estimates_risks
Revises: 0041_critic_review
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_estimates_risks"
down_revision: str | None = "0041_critic_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
RISKS = "estimates_risks"
CONVERTED_TO = "ck_gaps_gaps_converted_to"


def upgrade() -> None:
    op.drop_constraint(CONVERTED_TO, "gaps_gaps", type_="check")
    op.create_check_constraint(
        CONVERTED_TO,
        "gaps_gaps",
        "converted_to IS NULL OR converted_to IN ('condition', 'contingency', 'risk')",
    )

    op.add_column("estimates_assumptions", sa.Column("changed_by", sa.Uuid(), nullable=True))
    op.execute(f"GRANT DELETE ON estimates_assumptions TO {APP_ROLE}")

    op.create_table(
        RISKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("likelihood", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("origin_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("carried_from", sa.Uuid(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "likelihood IN ('low', 'medium', 'high')", name="ck_estimates_risks_likelihood"
        ),
        sa.CheckConstraint("impact IN ('low', 'medium', 'high')", name="ck_estimates_risks_impact"),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 1 AND 500", name="ck_estimates_risks_description"
        ),
        sa.CheckConstraint("position >= 1", name="ck_estimates_risks_position"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["estimates_estimate_versions.id"],
            name="fk_estimates_risks_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["carried_from"],
            ["estimates_risks.id"],
            name="fk_estimates_risks_carried_from",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimates_risks"),
        sa.UniqueConstraint("version_id", "position", name="uq_estimates_risks_version_id_position"),
    )
    op.create_index("ix_estimates_risks_version_id", RISKS, ["version_id"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {RISKS} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {RISKS} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_estimates_risks_version_id", RISKS)
    op.drop_table(RISKS)
    op.execute(f"REVOKE DELETE ON estimates_assumptions FROM {APP_ROLE}")
    op.drop_column("estimates_assumptions", "changed_by")
    # The older code has no Risks: their Gaps are open again.
    op.execute(
        "UPDATE gaps_gaps SET status = 'open', converted_to = NULL, "
        "row_version = row_version + 1 WHERE converted_to = 'risk'"
    )
    op.drop_constraint(CONVERTED_TO, "gaps_gaps", type_="check")
    op.create_check_constraint(
        CONVERTED_TO,
        "gaps_gaps",
        "converted_to IS NULL OR converted_to IN ('condition', 'contingency')",
    )
