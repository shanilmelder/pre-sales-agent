"""Marking Clarification Questions sent and "No answer" (Story 4.6, demo slice).

- `gaps_clarification_questions.status` gains `sent` and `unanswered`.
- `sent_on` (DATE) and `sent_by`: when and by whom the question was sent, set only while
  `sent | unanswered` (both or neither), enforced by
  `ck_gaps_clarification_questions_sent_fields`.
- `ck_gaps_clarification_questions_approved_iff_status` becomes "approval fields set iff the
  status is `approved | sent | unanswered`", so the approval is kept once a question is sent.

Grants unchanged: `psa_app` keeps SELECT, INSERT, UPDATE (no DELETE).

Downgrade returns sent and unanswered questions to `approved` (the older code has neither)
and drops the new columns.

Revision ID: 0030_gaps_question_sent
Revises: 0029_gaps_dismiss_history
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_gaps_question_sent"
down_revision: str | None = "0029_gaps_dismiss_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "gaps_clarification_questions"
STATUS = "ck_gaps_clarification_questions_status"
APPROVED_IFF_STATUS = "ck_gaps_clarification_questions_approved_iff_status"
SENT_FIELDS = "ck_gaps_clarification_questions_sent_fields"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("sent_on", sa.Date(), nullable=True))
    op.add_column(TABLE, sa.Column("sent_by", sa.Uuid(), nullable=True))
    op.drop_constraint(STATUS, TABLE, type_="check")
    op.create_check_constraint(
        STATUS,
        TABLE,
        "status IN ('drafted', 'approved', 'sent', 'unanswered', 'superseded')",
    )
    op.drop_constraint(APPROVED_IFF_STATUS, TABLE, type_="check")
    op.create_check_constraint(
        APPROVED_IFF_STATUS,
        TABLE,
        "(status IN ('approved', 'sent', 'unanswered')) = (approved_by IS NOT NULL)",
    )
    op.create_check_constraint(
        SENT_FIELDS,
        TABLE,
        "(status IN ('sent', 'unanswered')) = (sent_on IS NOT NULL) "
        "AND (sent_on IS NULL) = (sent_by IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(SENT_FIELDS, TABLE, type_="check")
    op.drop_constraint(APPROVED_IFF_STATUS, TABLE, type_="check")
    # Sent and unanswered questions go back to approved: the older code has neither.
    op.execute(f"UPDATE {TABLE} SET status = 'approved' WHERE status IN ('sent', 'unanswered')")
    op.create_check_constraint(
        APPROVED_IFF_STATUS, TABLE, "(status = 'approved') = (approved_by IS NOT NULL)"
    )
    op.drop_constraint(STATUS, TABLE, type_="check")
    op.create_check_constraint(STATUS, TABLE, "status IN ('drafted', 'approved', 'superseded')")
    op.drop_column(TABLE, "sent_by")
    op.drop_column(TABLE, "sent_on")
