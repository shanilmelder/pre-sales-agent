"""Review outcomes, replies and superseded requests (Story 9.4).

- `notifications_notifications.kind` gains `review_outcome` (a decision, to the
  Opportunity's owner and the request's sender) and `review_replied` (the author's reply, to
  the reviewer). The downgrade removes those items first.
- `reviews_review_requests.linked_request_id`: the request a newer one is an alternative to
  (an in-module foreign key; null for every other request).
- `reviews_review_replies`: append-only replies on a Review Request, each with a message (1
  to 2,000 characters), its Evidence (a jsonb list of `{kind, id, version}`), an optional
  alternative draft Estimate Version, who replied and when. `psa_app` gets SELECT and INSERT
  only: a reply is never changed or removed.

Revision ID: 0050_review_outcomes
Revises: 0049_reviews_review_decisions
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050_review_outcomes"
down_revision: str | None = "0049_reviews_review_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
NOTIFICATIONS = "notifications_notifications"
KIND_CHECK = "ck_notifications_notifications_kind"
OLD_KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated')"
)
KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated', 'review_outcome', 'review_replied')"
)
REQUESTS = "reviews_review_requests"
LINKED_FK = "fk_reviews_review_requests_linked_request_id"
REPLIES = "reviews_review_replies"


def upgrade() -> None:
    op.drop_constraint(KIND_CHECK, NOTIFICATIONS, type_="check")
    op.create_check_constraint(KIND_CHECK, NOTIFICATIONS, f"kind IN {KINDS}")

    op.add_column(REQUESTS, sa.Column("linked_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(LINKED_FK, REQUESTS, REQUESTS, ["linked_request_id"], ["id"])

    op.create_table(
        REPLIES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_request_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("alternative_version_id", sa.Uuid(), nullable=True),
        sa.Column("replied_by", sa.Uuid(), nullable=False),
        sa.Column(
            "replied_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(btrim(message)) >= 1 AND char_length(message) <= 2000",
            name="ck_reviews_review_replies_message",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array'", name="ck_reviews_review_replies_evidence"
        ),
        sa.ForeignKeyConstraint(
            ["review_request_id"],
            [f"{REQUESTS}.id"],
            name="fk_reviews_review_replies_review_request_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews_review_replies"),
    )
    op.create_index(
        "ix_reviews_review_replies_review_request_id_replied_at",
        REPLIES,
        ["review_request_id", "replied_at"],
    )
    op.execute(f"GRANT SELECT, INSERT ON {REPLIES} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {REPLIES} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_reviews_review_replies_review_request_id_replied_at", REPLIES)
    op.drop_table(REPLIES)
    op.drop_constraint(LINKED_FK, REQUESTS, type_="foreignkey")
    op.drop_column(REQUESTS, "linked_request_id")
    # The older code knows neither kind.
    op.execute(f"DELETE FROM {NOTIFICATIONS} WHERE kind IN ('review_outcome', 'review_replied')")
    op.drop_constraint(KIND_CHECK, NOTIFICATIONS, type_="check")
    op.create_check_constraint(KIND_CHECK, NOTIFICATIONS, f"kind IN {OLD_KINDS}")
