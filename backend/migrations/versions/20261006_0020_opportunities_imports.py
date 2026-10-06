"""Opportunity imports (Story 1.7, import from file).

`opportunities_imports`: one row per file uploaded on the New Opportunity form, read by the
`opportunities.read_import` job: its uploader (an identity user id, no foreign key across
modules, AD-2), the stored file (`file_sha256` in `platform.storage`, `size_bytes`), its
name, `status` (`queued`, `running`, `succeeded`, `failed` with an `error_code`), the
checked field suggestions (JSON), `created_at` and `consumed_at` (set once, when an
Opportunity is created from it).

`psa_app`: SELECT, INSERT, and UPDATE on only `status`, `error_code`, `suggestions` and
`consumed_at`. No DELETE (the 0002 default privileges are revoked).

Revision ID: 0020_opportunities_imports
Revises: 0019_estimates_line_edits
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_opportunities_imports"
down_revision: str | None = "0019_estimates_line_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "opportunities_imports"
JOB_TYPE = "opportunities.read_import"
UPDATABLE = "status, error_code, suggestions, consumed_at"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_opportunities_imports_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('unreadable', 'model_unavailable', 'model_timeout', 'output_invalid')",
            name="ck_opportunities_imports_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_opportunities_imports_failed_has_code",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_opportunities_imports_size_bytes"),
        sa.PrimaryKeyConstraint("id", name="pk_opportunities_imports"),
    )
    op.create_index(
        "ix_opportunities_imports_uploaded_by_created_at", TABLE, ["uploaded_by", "created_at"]
    )
    op.execute(f"REVOKE UPDATE, DELETE ON {TABLE} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({UPDATABLE}) ON {TABLE} TO {APP_ROLE}")


def downgrade() -> None:
    # Jobs for a type the older code doesn't have would only go dead.
    op.execute(
        "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        "lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_index("ix_opportunities_imports_uploaded_by_created_at", TABLE)
    op.drop_table(TABLE)
