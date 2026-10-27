"""Opportunity outcome and retention dates (Story 10.5).

`opportunities_opportunities` gains `outcome` (`won` or `lost`, null while the Opportunity is
open), `outcome_recorded_at` (set exactly when there is an outcome) and `contract_end_date`
(set exactly when it was won). The retention date is derived from them in domain code, never
stored. `psa_app` already has SELECT, INSERT, UPDATE and DELETE on the table.

Revision ID: 0056_opportunities_outcome
Revises: 0055_reporting_views
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056_opportunities_outcome"
down_revision: str | None = "0055_reporting_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPPORTUNITIES = "opportunities_opportunities"
OUTCOME_CHECK = "ck_opportunities_opportunities_outcome"
RECORDED_CHECK = "ck_opportunities_opportunities_outcome_recorded"
CONTRACT_CHECK = "ck_opportunities_opportunities_won_contract_end"


def upgrade() -> None:
    op.add_column(OPPORTUNITIES, sa.Column("outcome", sa.Text(), nullable=True))
    op.add_column(
        OPPORTUNITIES, sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(OPPORTUNITIES, sa.Column("contract_end_date", sa.Date(), nullable=True))
    op.create_check_constraint(OUTCOME_CHECK, OPPORTUNITIES, "outcome IN ('won', 'lost')")
    op.create_check_constraint(
        RECORDED_CHECK, OPPORTUNITIES, "(outcome IS NULL) = (outcome_recorded_at IS NULL)"
    )
    op.create_check_constraint(
        CONTRACT_CHECK,
        OPPORTUNITIES,
        "COALESCE(outcome = 'won', false) = (contract_end_date IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(CONTRACT_CHECK, OPPORTUNITIES, type_="check")
    op.drop_constraint(RECORDED_CHECK, OPPORTUNITIES, type_="check")
    op.drop_constraint(OUTCOME_CHECK, OPPORTUNITIES, type_="check")
    op.drop_column(OPPORTUNITIES, "contract_end_date")
    op.drop_column(OPPORTUNITIES, "outcome_recorded_at")
    op.drop_column(OPPORTUNITIES, "outcome")
