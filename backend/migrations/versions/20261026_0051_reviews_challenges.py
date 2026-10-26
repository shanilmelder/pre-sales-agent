"""Challenges (Story 9.5).

- `reviews_challenges`: a Challenge of an Estimate Version, an Assessment or one of its
  Findings, at a version, with the reason (1 to 1,000 characters), the Assessments the
  platform suggested rerunning (stored at raise) and the ones the owner confirmed, a decline
  reason, the Workflow Run the confirmation started, and its status
  (`awaiting_confirmation`, `reassessing`, `completed`, `declined`, `failed`). `psa_app`
  gets SELECT, INSERT and UPDATE; no DELETE.
- `workflows_runs` gains `run_type` (`assessment`, the default, or `challenge`),
  `trigger_ref` (the Challenge behind a challenge run) and `idempotency_key` (unique).
- `notifications_notifications.kind` gains `challenge_raised` and `challenge_declined`. The
  downgrade removes those items first.

Revision ID: 0051_reviews_challenges
Revises: 0050_review_outcomes
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_reviews_challenges"
down_revision: str | None = "0050_review_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
CHALLENGES = "reviews_challenges"
RUNS = "workflows_runs"
NOTIFICATIONS = "notifications_notifications"
KIND = "ck_notifications_notifications_kind"
OLD_KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated', 'review_outcome', 'review_replied')"
)
NEW_KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated', 'review_outcome', 'review_replied', 'challenge_raised', "
    "'challenge_declined')"
)
RUN_KEY_INDEX = "uq_workflows_runs_idempotency_key"


def upgrade() -> None:
    op.create_table(
        CHALLENGES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=True),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=False),
        sa.Column("review_request_id", sa.Uuid(), nullable=True),
        sa.Column("challenger_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "suggested",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("confirmed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "target_kind IN ('estimate_version', 'assessment', 'finding')",
            name="ck_reviews_challenges_target_kind",
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_confirmation', 'reassessing', 'completed', 'declined', "
            "'failed')",
            name="ck_reviews_challenges_status",
        ),
        sa.CheckConstraint(
            "char_length(btrim(reason)) >= 1 AND char_length(reason) <= 1000",
            name="ck_reviews_challenges_reason",
        ),
        sa.CheckConstraint(
            "(status = 'declined') = (decline_reason IS NOT NULL)",
            name="ck_reviews_challenges_declined_has_reason",
        ),
        sa.CheckConstraint(
            "decline_reason IS NULL OR (char_length(btrim(decline_reason)) >= 1 "
            "AND char_length(decline_reason) <= 1000)",
            name="ck_reviews_challenges_decline_reason",
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_confirmation', 'declined') OR workflow_run_id IS NOT NULL",
            name="ck_reviews_challenges_run_when_confirmed",
        ),
        sa.CheckConstraint("target_version >= 1", name="ck_reviews_challenges_target_version"),
        sa.ForeignKeyConstraint(
            ["review_request_id"],
            ["reviews_review_requests.id"],
            name="fk_reviews_challenges_review_request_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews_challenges"),
    )
    op.create_index("ix_reviews_challenges_opportunity_id", CHALLENGES, ["opportunity_id"])
    op.create_index("ix_reviews_challenges_review_request_id", CHALLENGES, ["review_request_id"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {CHALLENGES} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {CHALLENGES} FROM {APP_ROLE}")

    op.add_column(
        RUNS,
        sa.Column("run_type", sa.Text(), server_default=sa.text("'assessment'"), nullable=False),
    )
    op.add_column(RUNS, sa.Column("trigger_ref", sa.Uuid(), nullable=True))
    op.add_column(RUNS, sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_workflows_runs_run_type", RUNS, "run_type IN ('assessment', 'challenge')"
    )
    op.create_index(RUN_KEY_INDEX, RUNS, ["idempotency_key"], unique=True)

    op.drop_constraint(KIND, NOTIFICATIONS, type_="check")
    op.create_check_constraint(KIND, NOTIFICATIONS, f"kind IN {NEW_KINDS}")


def downgrade() -> None:
    # The older code knows neither kind.
    op.execute(
        f"DELETE FROM {NOTIFICATIONS} "  # noqa: S608 - module constants only
        "WHERE kind IN ('challenge_raised', 'challenge_declined')"
    )
    op.drop_constraint(KIND, NOTIFICATIONS, type_="check")
    op.create_check_constraint(KIND, NOTIFICATIONS, f"kind IN {OLD_KINDS}")

    op.drop_index(RUN_KEY_INDEX, RUNS)
    op.drop_constraint("ck_workflows_runs_run_type", RUNS, type_="check")
    op.drop_column(RUNS, "idempotency_key")
    op.drop_column(RUNS, "trigger_ref")
    op.drop_column(RUNS, "run_type")

    op.drop_index("ix_reviews_challenges_review_request_id", CHALLENGES)
    op.drop_index("ix_reviews_challenges_opportunity_id", CHALLENGES)
    op.drop_table(CHALLENGES)
