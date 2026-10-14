"""Changing impact, dismissing and reopening Gaps, with their history (Story 4.4, demo slice).

- `gaps_gaps.status` gains `dismissed`.
- `dismiss_reason_kind` (`not_relevant | other`), `dismiss_note`, `dismissed_by`,
  `dismissed_at`: set only while `dismissed`, all of them (the note required for `other`),
  enforced by `ck_gaps_gaps_dismissed_fields`.
- `changed_by`: the person behind the Gap's latest change, for the "Changed by {name}" of a
  412. `touched_by_human` (default false): set by an impact change or a reopen, so a later
  detection keeps the Gap.
- `gaps_gap_history`: insert-only rows of `impact_changed | dismissed | reopened |
  converted`, with who, when, the impacts, the dismissal reason kind and the reason or note.
  `psa_app`: SELECT, INSERT only.

Downgrade reopens dismissed Gaps (the older code has no `dismissed`) and drops the history
and the new columns.

Revision ID: 0029_gaps_dismiss_history
Revises: 0028_workflows
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_gaps_dismiss_history"
down_revision: str | None = "0028_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "gaps_gaps"
HISTORY = "gaps_gap_history"
DISMISSED_FIELDS = (
    "CASE WHEN status = 'dismissed' THEN "
    "dismiss_reason_kind IS NOT NULL AND dismissed_by IS NOT NULL AND dismissed_at IS NOT NULL "
    "AND (dismiss_reason_kind = 'not_relevant' OR dismiss_note IS NOT NULL) "
    "ELSE dismiss_reason_kind IS NULL AND dismiss_note IS NULL AND dismissed_by IS NULL "
    "AND dismissed_at IS NULL END"
)


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("dismiss_reason_kind", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("dismiss_note", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("dismissed_by", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("changed_by", sa.Uuid(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("touched_by_human", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint("ck_gaps_gaps_status", TABLE, type_="check")
    op.create_check_constraint(
        "ck_gaps_gaps_status",
        TABLE,
        "status IN ('open', 'superseded', 'converted', 'dismissed')",
    )
    op.create_check_constraint(
        "ck_gaps_gaps_dismiss_reason_kind",
        TABLE,
        "dismiss_reason_kind IS NULL OR dismiss_reason_kind IN ('not_relevant', 'other')",
    )
    op.create_check_constraint("ck_gaps_gaps_dismissed_fields", TABLE, DISMISSED_FIELDS)

    op.create_table(
        HISTORY,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gap_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("old_impact", sa.Text(), nullable=True),
        sa.Column("new_impact", sa.Text(), nullable=True),
        sa.Column("reason_kind", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('impact_changed', 'dismissed', 'reopened', 'converted')",
            name="ck_gaps_gap_history_kind",
        ),
        sa.ForeignKeyConstraint(
            ["gap_id"],
            ["gaps_gaps.id"],
            name="fk_gaps_gap_history_gap_id_gaps_gaps",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gaps_gap_history"),
    )
    op.create_index("ix_gaps_gap_history_gap_id_at", HISTORY, ["gap_id", "at"])
    op.execute(f"GRANT SELECT, INSERT ON {HISTORY} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {HISTORY} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_gaps_gap_history_gap_id_at", HISTORY)
    op.drop_table(HISTORY)
    op.drop_constraint("ck_gaps_gaps_dismissed_fields", TABLE, type_="check")
    op.drop_constraint("ck_gaps_gaps_dismiss_reason_kind", TABLE, type_="check")
    # Dismissed Gaps reopen: the older code has no `dismissed`.
    op.execute(
        f"UPDATE {TABLE} SET status = 'open', dismiss_reason_kind = NULL, dismiss_note = NULL, "
        "dismissed_by = NULL, dismissed_at = NULL WHERE status = 'dismissed'"
    )
    op.drop_constraint("ck_gaps_gaps_status", TABLE, type_="check")
    op.create_check_constraint(
        "ck_gaps_gaps_status", TABLE, "status IN ('open', 'superseded', 'converted')"
    )
    op.drop_column(TABLE, "touched_by_human")
    op.drop_column(TABLE, "changed_by")
    op.drop_column(TABLE, "dismissed_at")
    op.drop_column(TABLE, "dismissed_by")
    op.drop_column(TABLE, "dismiss_note")
    op.drop_column(TABLE, "dismiss_reason_kind")
