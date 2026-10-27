"""Actuals imports (Story 10.2; FR-49).

`actuals_imports`: one uploaded Actuals file (.xlsx or .csv) of an Opportunity, stored in
`platform.storage` by its SHA-256 and read by the `actuals.import_file` worker job. `status`
moves `queued -> running -> parsed` (or `failed`, with `error_code`), and `parsed -> applied`
once a delivery manager confirms it. `rows` holds the raw rows the job read (strings, by
column, with their sheet row number); the preview validates them afresh on every read.
`applied_at`, `applied_by` and the counts are set on apply. `psa_app` gets SELECT, INSERT and
UPDATE (status changes); never DELETE.

User ids carry no foreign key (AD-2); the Opportunity does.

Revision ID: 0054_actuals_imports
Revises: 0053_actuals_actuals
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054_actuals_imports"
down_revision: str | None = "0053_actuals_actuals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
IMPORTS = "actuals_imports"


def upgrade() -> None:
    op.create_table(
        IMPORTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.Uuid(), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=True),
        sa.Column("corrected_count", sa.Integer(), nullable=True),
        sa.Column("excluded_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.CheckConstraint("file_kind IN ('xlsx', 'csv')", name="ck_actuals_imports_file_kind"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'parsed', 'failed', 'applied')",
            name="ck_actuals_imports_status",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_actuals_imports_size_bytes"),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_actuals_imports_failed_has_code",
        ),
        sa.CheckConstraint(
            "(status = 'applied') = (applied_at IS NOT NULL)",
            name="ck_actuals_imports_applied_at",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities_opportunities.id"],
            name="fk_actuals_imports_opportunity_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_actuals_imports"),
    )
    op.create_index(
        "ix_actuals_imports_opportunity_id_created_at", IMPORTS, ["opportunity_id", "created_at"]
    )
    op.create_index(
        "ix_actuals_imports_opportunity_id_file_sha256", IMPORTS, ["opportunity_id", "file_sha256"]
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {IMPORTS} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {IMPORTS} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_actuals_imports_opportunity_id_file_sha256", IMPORTS)
    op.drop_index("ix_actuals_imports_opportunity_id_created_at", IMPORTS)
    op.drop_table(IMPORTS)
