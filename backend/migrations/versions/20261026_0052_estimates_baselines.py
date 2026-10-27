"""The Baseline (Story 9.7; AD-26).

`estimates_baselines`: one row each time a person sets an approved Estimate Version as the
Opportunity's Baseline, with the version it replaced (null for the first), when and by whom.
The Opportunity's current Baseline is its latest row (index on `(opportunity_id, set_at
DESC)`). `psa_app` gets SELECT and INSERT only: a Baseline is never changed or removed, only
replaced by a newer row.

Revision ID: 0052_estimates_baselines
Revises: 0051_reviews_challenges
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_estimates_baselines"
down_revision: str | None = "0051_reviews_challenges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
BASELINES = "estimates_baselines"
VERSIONS = "estimates_estimate_versions"
INDEX = "ix_estimates_baselines_opportunity_id_set_at"


def upgrade() -> None:
    op.create_table(
        BASELINES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=False),
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "set_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("set_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities_opportunities.id"],
            name="fk_estimates_baselines_opportunity_id",
        ),
        sa.ForeignKeyConstraint(
            ["estimate_version_id"],
            [f"{VERSIONS}.id"],
            name="fk_estimates_baselines_estimate_version_id",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            [f"{VERSIONS}.id"],
            name="fk_estimates_baselines_previous_version_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimates_baselines"),
    )
    op.create_index(
        INDEX,
        BASELINES,
        ["opportunity_id", sa.text("set_at DESC")],
    )
    op.execute(f"GRANT SELECT, INSERT ON {BASELINES} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {BASELINES} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(INDEX, BASELINES)
    op.drop_table(BASELINES)
