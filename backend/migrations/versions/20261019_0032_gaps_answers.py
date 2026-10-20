"""Answering Clarification Questions (Story 4.7, demo slice).

- `gaps_clarification_questions.status` gains `answered`. `answered_on` (DATE), `answered_by`
  and `answer_passage_id` (an `intake_source_passages` id, no foreign key: AD-2) are set
  only while `answered`, all or none (`ck_gaps_clarification_questions_answered_fields`).
  The approval and sent checks are widened so both are kept once a question is answered.
- `gaps_gaps.status` gains `answered`, with the same three fields
  (`ck_gaps_gaps_answered_fields`).
- `gaps_gap_history.kind` gains `answered`.
- `gaps_answer_matches`: `clarification_agent`'s suggestion that a Source passage answers a
  question (`suggested | confirmed | rejected | superseded`), whether the passage looks like
  an injection attempt, who decided and when, and a `row_version`. One row per (question,
  passage), so a rejected pair never returns. `psa_app`: SELECT, INSERT, UPDATE (no DELETE).

Downgrade drops the table, returns answered questions to `sent` and answered Gaps to `open`
(the older code has no answers), deletes `answered` history rows, drops the columns, and
makes `clarification_answer` Sources `note` Sources (the older code has no such kind).

Revision ID: 0032_gaps_answers
Revises: 0031_intake_requirement_changes
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_gaps_answers"
down_revision: str | None = "0031_intake_requirement_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
QUESTIONS = "gaps_clarification_questions"
GAPS = "gaps_gaps"
HISTORY = "gaps_gap_history"
MATCHES = "gaps_answer_matches"

Q_STATUS = "ck_gaps_clarification_questions_status"
Q_APPROVED = "ck_gaps_clarification_questions_approved_iff_status"
Q_SENT = "ck_gaps_clarification_questions_sent_fields"
Q_ANSWERED = "ck_gaps_clarification_questions_answered_fields"
G_STATUS = "ck_gaps_gaps_status"
G_ANSWERED = "ck_gaps_gaps_answered_fields"
H_KIND = "ck_gaps_gap_history_kind"

ANSWERED_FIELDS = (
    "(status = 'answered') = (answered_on IS NOT NULL) "
    "AND (answered_on IS NULL) = (answered_by IS NULL) "
    "AND (answered_on IS NULL) = (answer_passage_id IS NULL)"
)


def _answer_columns(table: str) -> None:
    op.add_column(table, sa.Column("answered_on", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("answered_by", sa.Uuid(), nullable=True))
    op.add_column(table, sa.Column("answer_passage_id", sa.Uuid(), nullable=True))


def _replace_check(name: str, table: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    _answer_columns(QUESTIONS)
    _replace_check(
        Q_STATUS,
        QUESTIONS,
        "status IN ('drafted', 'approved', 'sent', 'unanswered', 'answered', 'superseded')",
    )
    _replace_check(
        Q_APPROVED,
        QUESTIONS,
        "(status IN ('approved', 'sent', 'unanswered', 'answered')) = (approved_by IS NOT NULL)",
    )
    _replace_check(
        Q_SENT,
        QUESTIONS,
        "(status IN ('sent', 'unanswered', 'answered')) = (sent_on IS NOT NULL) "
        "AND (sent_on IS NULL) = (sent_by IS NULL)",
    )
    op.create_check_constraint(Q_ANSWERED, QUESTIONS, ANSWERED_FIELDS)

    _answer_columns(GAPS)
    _replace_check(
        G_STATUS, GAPS, "status IN ('open', 'superseded', 'converted', 'dismissed', 'answered')"
    )
    op.create_check_constraint(G_ANSWERED, GAPS, ANSWERED_FIELDS)

    _replace_check(
        H_KIND, HISTORY, "kind IN ('impact_changed', 'dismissed', 'reopened', 'converted', 'answered')"
    )

    op.create_table(
        MATCHES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("passage_id", sa.Uuid(), nullable=False),
        sa.Column(
            "injection_suspected", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected', 'superseded')",
            name="ck_gaps_answer_matches_status",
        ),
        sa.CheckConstraint(
            "(status IN ('confirmed', 'rejected')) = (decided_by IS NOT NULL) "
            "AND (decided_by IS NULL) = (decided_at IS NULL)",
            name="ck_gaps_answer_matches_decided_fields",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            [f"{QUESTIONS}.id"],
            name="fk_gaps_answer_matches_question_id_gaps_clarification_questions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gaps_answer_matches"),
        sa.UniqueConstraint(
            "question_id", "passage_id", name="uq_gaps_answer_matches_question_id_passage_id"
        ),
    )
    op.create_index(
        "ix_gaps_answer_matches_opportunity_id_status", MATCHES, ["opportunity_id", "status"]
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {MATCHES} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {MATCHES} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_gaps_answer_matches_opportunity_id_status", MATCHES)
    op.drop_table(MATCHES)

    op.execute("UPDATE intake_sources SET kind = 'note' WHERE kind = 'clarification_answer'")
    op.execute(f"DELETE FROM {HISTORY} WHERE kind = 'answered'")
    _replace_check(
        H_KIND, HISTORY, "kind IN ('impact_changed', 'dismissed', 'reopened', 'converted')"
    )

    op.drop_constraint(G_ANSWERED, GAPS, type_="check")
    op.execute(f"UPDATE {GAPS} SET status = 'open' WHERE status = 'answered'")
    _replace_check(G_STATUS, GAPS, "status IN ('open', 'superseded', 'converted', 'dismissed')")
    for column in ("answer_passage_id", "answered_by", "answered_on"):
        op.drop_column(GAPS, column)

    op.drop_constraint(Q_ANSWERED, QUESTIONS, type_="check")
    op.execute(f"UPDATE {QUESTIONS} SET status = 'sent' WHERE status = 'answered'")
    _replace_check(
        Q_SENT,
        QUESTIONS,
        "(status IN ('sent', 'unanswered')) = (sent_on IS NOT NULL) "
        "AND (sent_on IS NULL) = (sent_by IS NULL)",
    )
    _replace_check(
        Q_APPROVED,
        QUESTIONS,
        "(status IN ('approved', 'sent', 'unanswered')) = (approved_by IS NOT NULL)",
    )
    _replace_check(
        Q_STATUS,
        QUESTIONS,
        "status IN ('drafted', 'approved', 'sent', 'unanswered', 'superseded')",
    )
    for column in ("answer_passage_id", "answered_by", "answered_on"):
        op.drop_column(QUESTIONS, column)
