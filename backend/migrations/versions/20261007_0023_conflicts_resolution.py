"""People resolve and escalate Conflicts (Story 6.3, demo slice).

`conflicts_conflicts` gains, all nullable:

- the decision: `resolved_by` (the user who resolved it; null when the system did),
  `chosen_position` (one of its position numbers) or `entered_position` (a different position
  in words; at most one of the two), and `applied_hours` (the hours an `effort` decision set
  on the Estimate line, or null when it changed no line);
- the escalation: `escalated_to` (the named reviewer), `escalated_by`, `escalated_at` and
  `escalation_reason`, all set or all null.

User ids are identity ids without foreign keys (AD-2). `psa_app` gets UPDATE on the new
columns too (still no DELETE).

Revision ID: 0023_conflicts_resolution
Revises: 0022_estimates_from_assessments
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_conflicts_resolution"
down_revision: str | None = "0022_estimates_from_assessments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "conflicts_conflicts"
NEW_COLUMNS = (
    "resolved_by",
    "chosen_position",
    "entered_position",
    "applied_hours",
    "escalated_to",
    "escalated_by",
    "escalated_at",
    "escalation_reason",
)


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("resolved_by", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("chosen_position", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("entered_position", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("applied_hours", sa.Numeric(10, 1), nullable=True))
    op.add_column(TABLE, sa.Column("escalated_to", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("escalated_by", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("escalation_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_conflicts_conflicts_escalation",
        TABLE,
        "(escalated_to IS NULL) = (escalated_by IS NULL) AND "
        "(escalated_to IS NULL) = (escalated_at IS NULL) AND "
        "(escalated_to IS NULL) = (escalation_reason IS NULL)",
    )
    op.create_check_constraint(
        "ck_conflicts_conflicts_one_choice",
        TABLE,
        "chosen_position IS NULL OR entered_position IS NULL",
    )
    op.execute(f"GRANT UPDATE ({', '.join(NEW_COLUMNS)}) ON {TABLE} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({', '.join(NEW_COLUMNS)}) ON {TABLE} FROM {APP_ROLE}")
    op.drop_constraint("ck_conflicts_conflicts_one_choice", TABLE, type_="check")
    op.drop_constraint("ck_conflicts_conflicts_escalation", TABLE, type_="check")
    for column in reversed(NEW_COLUMNS):
        op.drop_column(TABLE, column)
