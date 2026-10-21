"""Requirement lifecycle (Story 2.6 remainder): delete, split, merge and stable numbers.

- `intake_requirements.status` gains `deleted` (a person removed it with a reason).
- `intake_requirements.removal_reason` (nullable): why a person deleted it; set exactly when
  the status is `deleted` (`ck_intake_requirements_deleted_has_reason`).
- `intake_requirements.number`: the Requirement's stable `R<n>` within its Opportunity,
  never reused (`uq_intake_requirements_opportunity_id_number`, `>= 1`). Backfilled from
  today's labels: the active Requirements by `created_at, id` are 1..N, the inactive ones
  follow in the same order, so no label shown today changes.

Downgrade turns `deleted` Requirements into `superseded` ones (the older code reads both as
no longer active) and drops the columns.

Revision ID: 0034_requirement_lifecycle
Revises: 0033_conflict_agent
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_requirement_lifecycle"
down_revision: str | None = "0033_conflict_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "intake_requirements"
STATUS = "ck_intake_requirements_status"
REASON = "ck_intake_requirements_deleted_has_reason"
NUMBER = "ck_intake_requirements_number"
UNIQUE_NUMBER = "uq_intake_requirements_opportunity_id_number"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("removal_reason", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("number", sa.Integer(), nullable=True))
    op.execute(
        f"""
        UPDATE {TABLE} AS r SET number = n.rn
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY opportunity_id
                ORDER BY (status <> 'active'), created_at, id
            ) AS rn
            FROM {TABLE}
        ) AS n
        WHERE r.id = n.id
        """
    )
    op.alter_column(TABLE, "number", nullable=False)
    op.create_unique_constraint(UNIQUE_NUMBER, TABLE, ["opportunity_id", "number"])
    op.create_check_constraint(NUMBER, TABLE, "number >= 1")
    op.drop_constraint(STATUS, TABLE, type_="check")
    op.create_check_constraint(STATUS, TABLE, "status IN ('active', 'superseded', 'deleted')")
    op.create_check_constraint(
        REASON, TABLE, "(status = 'deleted') = (removal_reason IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_constraint(REASON, TABLE, type_="check")
    op.execute(f"UPDATE {TABLE} SET status = 'superseded' WHERE status = 'deleted'")
    op.drop_constraint(STATUS, TABLE, type_="check")
    op.create_check_constraint(STATUS, TABLE, "status IN ('active', 'superseded')")
    op.drop_constraint(NUMBER, TABLE, type_="check")
    op.drop_constraint(UNIQUE_NUMBER, TABLE, type_="unique")
    op.drop_column(TABLE, "number")
    op.drop_column(TABLE, "removal_reason")
