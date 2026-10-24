"""Config version reason and restore source (Story 7.3).

`registry_agent_config_versions` gains two nullable columns:

- `reason` (text, 1-500 characters): why an administrator created the version. Seeded and
  earlier rows keep null (shown as "—").
- `restored_from_version` (int): the version a restore copied, an earlier version of the
  same Agent; null unless the version is a restore.

The table stays insert-only; `psa_app` already has SELECT and INSERT on it, so the grants
are unchanged. Downgrade drops both columns (and their checks).

Revision ID: 0044_registry_config_reason
Revises: 0043_estimates_risks
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_registry_config_reason"
down_revision: str | None = "0043_estimates_risks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "registry_agent_config_versions"
CHECKS = {
    "ck_registry_agent_config_versions_reason": (
        "reason IS NULL OR char_length(reason) BETWEEN 1 AND 500"
    ),
    "ck_registry_agent_config_versions_restored_from_version": (
        "restored_from_version IS NULL "
        "OR (restored_from_version >= 1 AND restored_from_version < version)"
    ),
}


def upgrade() -> None:
    op.add_column(VERSIONS, sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(VERSIONS, sa.Column("restored_from_version", sa.Integer(), nullable=True))
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, VERSIONS, condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, VERSIONS, type_="check")
    op.drop_column(VERSIONS, "restored_from_version")
    op.drop_column(VERSIONS, "reason")
