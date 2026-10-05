"""Editing and approving Clarification Questions (Story 4.5, demo slice).

- `gaps_clarification_questions.status` gains `approved` (`drafted | approved | superseded`).
- `approved_by` / `approved_at`: who approved it and when, set only while `approved` (both or
  neither).
- `edited_by_human`: a person changed its text or topic (default false). A later detection
  keeps the Gap of an edited or approved question instead of superseding it.
- `changed_by`: the person behind its latest edit or approval (null until then), for the
  "Changed by {name}" of a 412.

Grants unchanged: `psa_app` keeps SELECT, INSERT, UPDATE (no DELETE).

Revision ID: 0016_gaps_question_approval
Revises: 0015_estimates_carry_assumptions
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_gaps_question_approval"
down_revision: str | None = "0015_estimates_carry_assumptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "gaps_clarification_questions"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("approved_by", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "edited_by_human", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(TABLE, sa.Column("changed_by", sa.Uuid(), nullable=True))
    op.drop_constraint("ck_gaps_clarification_questions_status", TABLE, type_="check")
    op.create_check_constraint(
        "ck_gaps_clarification_questions_status",
        TABLE,
        "status IN ('drafted', 'approved', 'superseded')",
    )
    op.create_check_constraint(
        "ck_gaps_clarification_questions_approved_has_by",
        TABLE,
        "(approved_at IS NULL) = (approved_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_gaps_clarification_questions_approved_iff_status",
        TABLE,
        "(status = 'approved') = (approved_by IS NOT NULL)",
    )


def downgrade() -> None:
    # Approved questions go back to drafted: the older code has no `approved`.
    op.drop_constraint(
        "ck_gaps_clarification_questions_approved_iff_status", TABLE, type_="check"
    )
    op.drop_constraint("ck_gaps_clarification_questions_approved_has_by", TABLE, type_="check")
    op.execute(f"UPDATE {TABLE} SET status = 'drafted' WHERE status = 'approved'")
    op.drop_constraint("ck_gaps_clarification_questions_status", TABLE, type_="check")
    op.create_check_constraint(
        "ck_gaps_clarification_questions_status", TABLE, "status IN ('drafted', 'superseded')"
    )
    op.drop_column(TABLE, "changed_by")
    op.drop_column(TABLE, "edited_by_human")
    op.drop_column(TABLE, "approved_at")
    op.drop_column(TABLE, "approved_by")
