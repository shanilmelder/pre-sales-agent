"""Estimate Versions built from the specialist Assessments (Story 8.3, demo slice).

`estimates_estimate_versions` gains `source` (`model` or `assessments`, default `model`, so
every existing version reads as a model draft) and `source_run_id` (the assessment run a
version from the Assessments was built for, an assessments id with no foreign key, AD-2; null
for a model draft; set exactly when `source` is `assessments`).

`psa_app` already has SELECT, INSERT and UPDATE on the table (0012); still no DELETE.

Revision ID: 0022_estimates_from_assessments
Revises: 0021_conflicts
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_estimates_from_assessments"
down_revision: str | None = "0021_conflicts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "estimates_estimate_versions"


def upgrade() -> None:
    op.add_column(
        VERSIONS,
        sa.Column("source", sa.Text(), server_default=sa.text("'model'"), nullable=False),
    )
    op.add_column(VERSIONS, sa.Column("source_run_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_estimates_estimate_versions_source", VERSIONS, "source IN ('model', 'assessments')"
    )
    op.create_check_constraint(
        "ck_estimates_estimate_versions_source_has_run",
        VERSIONS,
        "(source = 'assessments') = (source_run_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_estimates_estimate_versions_source_has_run", VERSIONS, type_="check")
    op.drop_constraint("ck_estimates_estimate_versions_source", VERSIONS, type_="check")
    op.drop_column(VERSIONS, "source_run_id")
    op.drop_column(VERSIONS, "source")
