"""Review Decisions (Story 9.3).

- `reviews_review_decisions`: append-only decisions on a Review Request (`approved`,
  `rejected`, `challenged`, `evidence_requested`, `alternative_requested`, `escalated`), each
  with the reviewer, the target version and, for every decision but `approved`, a reason
  (at most 1,000 characters); `escalated_to` is set for, and only for, an escalation.
  `psa_app` gets SELECT and INSERT only: a decision is never changed or removed.
- `estimates_estimate_versions.status` gains `approved` and `rejected`. The downgrade maps
  both back to `in_review`.

Revision ID: 0049_reviews_review_decisions
Revises: 0048_notifications
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_reviews_review_decisions"
down_revision: str | None = "0048_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
DECISIONS = "reviews_review_decisions"
VERSIONS = "estimates_estimate_versions"
STATUS = "ck_estimates_estimate_versions_status"


def upgrade() -> None:
    op.create_table(
        DECISIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_request_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("escalated_to", sa.Uuid(), nullable=True),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'challenged', 'evidence_requested', "
            "'alternative_requested', 'escalated')",
            name="ck_reviews_review_decisions_decision",
        ),
        sa.CheckConstraint(
            "decision = 'approved' OR (reason IS NOT NULL AND char_length(btrim(reason)) >= 1)",
            name="ck_reviews_review_decisions_reason_required",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) <= 1000",
            name="ck_reviews_review_decisions_reason",
        ),
        sa.CheckConstraint(
            "(decision = 'escalated') = (escalated_to IS NOT NULL)",
            name="ck_reviews_review_decisions_escalated_has_target",
        ),
        sa.CheckConstraint(
            "target_version >= 1", name="ck_reviews_review_decisions_target_version"
        ),
        sa.ForeignKeyConstraint(
            ["review_request_id"],
            ["reviews_review_requests.id"],
            name="fk_reviews_review_decisions_review_request_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews_review_decisions"),
    )
    op.create_index(
        "ix_reviews_review_decisions_review_request_id_decided_at",
        DECISIONS,
        ["review_request_id", "decided_at"],
    )
    op.execute(f"GRANT SELECT, INSERT ON {DECISIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {DECISIONS} FROM {APP_ROLE}")

    op.drop_constraint(STATUS, VERSIONS, type_="check")
    op.create_check_constraint(
        STATUS,
        VERSIONS,
        "status IN ('draft', 'submitted', 'in_review', 'approved', 'rejected', 'superseded')",
    )


def downgrade() -> None:
    # The older code knows neither status: a decided version reads as still in review.
    op.execute(f"UPDATE {VERSIONS} SET status = 'in_review' WHERE status IN ('approved', 'rejected')")
    op.drop_constraint(STATUS, VERSIONS, type_="check")
    op.create_check_constraint(
        STATUS, VERSIONS, "status IN ('draft', 'submitted', 'in_review', 'superseded')"
    )
    op.drop_index("ix_reviews_review_decisions_review_request_id_decided_at", DECISIONS)
    op.drop_table(DECISIONS)
