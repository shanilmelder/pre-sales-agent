"""Submitted Estimate Versions (Story 8.6).

`estimates_estimate_versions.status` gains `submitted`: `estimates.submit_version` moves the
draft there once the submission blockers are clear, and marks earlier `submitted` versions
`superseded`. `submitted_at` (null until then) records when; it stays set once the version is
superseded, and a `submitted` version always has it. The one-draft partial index is
unchanged.

`psa_app` already has SELECT, INSERT and UPDATE on the table (0012); still no DELETE.

Revision ID: 0044_submitted_status
Revises: 0043_estimates_risks
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_submitted_status"
down_revision: str | None = "0043_estimates_risks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "estimates_estimate_versions"
STATUS = "ck_estimates_estimate_versions_status"
SUBMITTED_AT = "ck_estimates_estimate_versions_submitted_has_at"


def upgrade() -> None:
    op.drop_constraint(STATUS, VERSIONS, type_="check")
    op.create_check_constraint(STATUS, VERSIONS, "status IN ('draft', 'submitted', 'superseded')")
    op.add_column(VERSIONS, sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        SUBMITTED_AT, VERSIONS, "status <> 'submitted' OR submitted_at IS NOT NULL"
    )


def downgrade() -> None:
    # A submitted version reads as superseded once the status is gone: it is no longer the
    # draft, and the earlier rule allowed nothing else.
    op.execute(f"UPDATE {VERSIONS} SET status = 'superseded' WHERE status = 'submitted'")
    op.drop_constraint(SUBMITTED_AT, VERSIONS, type_="check")
    op.drop_column(VERSIONS, "submitted_at")
    op.drop_constraint(STATUS, VERSIONS, type_="check")
    op.create_check_constraint(STATUS, VERSIONS, "status IN ('draft', 'superseded')")
