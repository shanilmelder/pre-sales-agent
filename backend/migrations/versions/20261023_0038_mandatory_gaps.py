"""Deterministic Gaps from mandatory Checklist items (Story 4.2).

- `gaps_gaps.origin` gains `mandatory_checklist`.
- `gaps_gaps.checklist_applies` (BOOLEAN, default true): whether an open mandatory Gap's
  Checklist item is still a mandatory item of an applicable version.
- `gaps_gaps.why_entry_id` (UUID, null): the catalogue entry the Gap's `why_it_matters`
  names (no foreign key: AD-2).
- `gaps_clarification_questions.from_checklist` (BOOLEAN, default false): drafted from the
  Checklist item's wording.
- `uq_gaps_gaps_mandatory_item`: unique partial index on `(opportunity_id,
  trigger->>'checklist_id', trigger->>'item_id') WHERE origin = 'mandatory_checklist'`, so
  reruns and concurrent runs raise one Gap per item.

Downgrade deletes the mandatory Gaps (the older code can't read their trigger), with their
questions, history and Requirement links (cascade), then drops the columns and the index.

Revision ID: 0038_mandatory_gaps
Revises: 0037_requirement_tags
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_mandatory_gaps"
down_revision: str | None = "0037_requirement_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GAPS = "gaps_gaps"
QUESTIONS = "gaps_clarification_questions"
ORIGIN = "ck_gaps_gaps_origin"
INDEX = "uq_gaps_gaps_mandatory_item"


def upgrade() -> None:
    op.drop_constraint(ORIGIN, GAPS, type_="check")
    op.create_check_constraint(ORIGIN, GAPS, "origin IN ('detected', 'mandatory_checklist')")
    op.add_column(
        GAPS,
        sa.Column(
            "checklist_applies", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.add_column(GAPS, sa.Column("why_entry_id", sa.Uuid(), nullable=True))
    op.add_column(
        QUESTIONS,
        sa.Column(
            "from_checklist", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_index(
        INDEX,
        GAPS,
        ["opportunity_id", sa.text("(trigger ->> 'checklist_id')"), sa.text("(trigger ->> 'item_id')")],
        unique=True,
        postgresql_where=sa.text("origin = 'mandatory_checklist'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, GAPS)
    op.execute(f"DELETE FROM {GAPS} WHERE origin = 'mandatory_checklist'")
    op.drop_column(QUESTIONS, "from_checklist")
    op.drop_column(GAPS, "why_entry_id")
    op.drop_column(GAPS, "checklist_applies")
    op.drop_constraint(ORIGIN, GAPS, type_="check")
    op.create_check_constraint(ORIGIN, GAPS, "origin IN ('detected')")
