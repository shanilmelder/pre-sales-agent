"""Carried Assumptions (Story 8.7, demo slice).

- `estimates_assumptions.carried_from`: the accepted Assumption of the superseded version a
  re-draft copied this one from (a foreign key to `estimates_assumptions.id`, ON DELETE SET
  NULL so a version's cascade delete still works), null for a proposal. Grants unchanged: `psa_app` keeps SELECT, INSERT, UPDATE (no DELETE).

Revision ID: 0015_estimates_carry_assumptions
Revises: 0014_assessments_red_team
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_estimates_carry_assumptions"
down_revision: str | None = "0014_assessments_red_team"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("estimates_assumptions", sa.Column("carried_from", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_estimates_assumptions_carried_from",
        "estimates_assumptions",
        "estimates_assumptions",
        ["carried_from"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_estimates_assumptions_carried_from", "estimates_assumptions", type_="foreignkey"
    )
    op.drop_column("estimates_assumptions", "carried_from")
