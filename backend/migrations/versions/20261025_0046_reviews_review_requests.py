"""Review Requests (Story 9.1).

- `reviews_review_requests`: one request per reviewer and target (an Estimate Version, or one
  of its Assessments at a version), counting towards `estimate_version_id`. `psa_app` gets
  SELECT, INSERT and UPDATE; no DELETE (a request is cancelled, never removed). At most one
  `pending` request per reviewer, review type and target.
- `estimates_estimate_versions.status` gains `in_review` (a submitted version with a pending
  Review Request); `created_by` (nullable) records the person who triggered the version. It is
  backfilled from the user actor of the version's `estimates.estimate_version.created` trace
  event, else the user who started its assessment run (plan v1's creator); otherwise it stays
  NULL (unknown author, no author check). `estimates_drafts.requested_by` (nullable, no
  backfill) records who started a model draft (`start_draft`), which becomes its
  version's `created_by`; drafts queued by the platform leave it NULL.
- `opportunities_collaborators.role`: `collaborator` (the existing rows) or `reviewer` (read
  only, granted while a Review Request is pending).

Revision ID: 0046_reviews_review_requests
Revises: 0045_registry_config_reason
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_reviews_review_requests"
down_revision: str | None = "0045_registry_config_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
REQUESTS = "reviews_review_requests"
VERSIONS = "estimates_estimate_versions"
DRAFTS = "estimates_drafts"
STATUS = "ck_estimates_estimate_versions_status"
COLLABORATORS = "opportunities_collaborators"
COLLABORATOR_ROLE = "ck_opportunities_collaborators_role"
UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def upgrade() -> None:
    op.create_table(
        REQUESTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("review_type", sa.Text(), nullable=False),
        sa.Column("target_kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("estimate_version_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "review_type IN ('engineering', 'pm', 'security')",
            name="ck_reviews_review_requests_review_type",
        ),
        sa.CheckConstraint(
            "target_kind IN ('estimate_version', 'assessment')",
            name="ck_reviews_review_requests_target_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'challenged', 'superseded', "
            "'cancelled')",
            name="ck_reviews_review_requests_status",
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)",
            name="ck_reviews_review_requests_cancelled_has_reason",
        ),
        sa.CheckConstraint(
            "message IS NULL OR char_length(message) <= 2000",
            name="ck_reviews_review_requests_message",
        ),
        sa.CheckConstraint("target_version >= 1", name="ck_reviews_review_requests_target_version"),
        sa.PrimaryKeyConstraint("id", name="pk_reviews_review_requests"),
    )
    op.create_index("ix_reviews_review_requests_opportunity_id", REQUESTS, ["opportunity_id"])
    op.create_index(
        "ix_reviews_review_requests_estimate_version_id", REQUESTS, ["estimate_version_id"]
    )
    op.create_index("ix_reviews_review_requests_reviewer_id", REQUESTS, ["reviewer_id"])
    op.create_index(
        "uq_reviews_review_requests_one_pending",
        REQUESTS,
        ["reviewer_id", "review_type", "target_kind", "target_id", "target_version"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {REQUESTS} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {REQUESTS} FROM {APP_ROLE}")

    op.drop_constraint(STATUS, VERSIONS, type_="check")
    op.create_check_constraint(
        STATUS, VERSIONS, "status IN ('draft', 'submitted', 'in_review', 'superseded')"
    )
    op.add_column(VERSIONS, sa.Column("created_by", sa.Uuid(), nullable=True))
    op.add_column(DRAFTS, sa.Column("requested_by", sa.Uuid(), nullable=True))
    op.execute(
        f"""
        UPDATE {VERSIONS} AS v SET created_by = COALESCE(
            (SELECT CAST(e.actor_id AS uuid) FROM platform_trace_events AS e
              WHERE e.subject_type = 'estimates.estimate_version' AND e.subject_id = v.id
                AND e.event_type = 'estimates.estimate_version.created'
                AND e.actor_type = 'user' AND e.actor_id ~ '{UUID_RE}'
              ORDER BY e.occurred_at, e.id LIMIT 1),
            (SELECT CAST(p.created_by AS uuid) FROM workflows_plan_versions AS p
              WHERE p.run_id = v.source_run_id AND p.version = 1
                AND p.created_by_type = 'user' AND p.created_by ~ '{UUID_RE}'
              LIMIT 1)
        )
        WHERE v.created_by IS NULL
        """
    )

    op.add_column(
        COLLABORATORS,
        sa.Column("role", sa.Text(), server_default=sa.text("'collaborator'"), nullable=False),
    )
    op.create_check_constraint(
        COLLABORATOR_ROLE, COLLABORATORS, "role IN ('collaborator', 'reviewer')"
    )


def downgrade() -> None:
    # Reviewers were only ever granted read access for a request; the older code has neither.
    op.execute(f"DELETE FROM {COLLABORATORS} WHERE role = 'reviewer'")
    op.drop_constraint(COLLABORATOR_ROLE, COLLABORATORS, type_="check")
    op.drop_column(COLLABORATORS, "role")

    # An in-review version reads as submitted once the status is gone.
    op.execute(f"UPDATE {VERSIONS} SET status = 'submitted' WHERE status = 'in_review'")
    op.drop_column(DRAFTS, "requested_by")
    op.drop_column(VERSIONS, "created_by")
    op.drop_constraint(STATUS, VERSIONS, type_="check")
    op.create_check_constraint(STATUS, VERSIONS, "status IN ('draft', 'submitted', 'superseded')")

    op.drop_index("uq_reviews_review_requests_one_pending", REQUESTS)
    op.drop_index("ix_reviews_review_requests_reviewer_id", REQUESTS)
    op.drop_index("ix_reviews_review_requests_estimate_version_id", REQUESTS)
    op.drop_index("ix_reviews_review_requests_opportunity_id", REQUESTS)
    op.drop_table(REQUESTS)
