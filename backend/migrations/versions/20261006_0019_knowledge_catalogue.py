"""The Integration Type and Work Package catalogue (Story 3.1).

- `knowledge_catalogue_entries`: the mutable header (`kind`, never-changing `code`, `status`
  `active | retired`, `retired_reason` set exactly when retired, `row_version`). `psa_app`:
  SELECT, INSERT, UPDATE (no DELETE).
- `knowledge_catalogue_entry_versions`: immutable name and definition per version, unique
  `(entry_id, version)`. `psa_app`: SELECT, INSERT only.

Revision ID: 0019_knowledge_catalogue
Revises: 0018_assessments_cancel
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_knowledge_catalogue"
down_revision: str | None = "0018_assessments_cancel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
ENTRIES = "knowledge_catalogue_entries"
VERSIONS = "knowledge_catalogue_entry_versions"


def upgrade() -> None:
    op.create_table(
        ENTRIES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retired_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('integration_type', 'work_package')",
            name="ck_knowledge_catalogue_entries_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')", name="ck_knowledge_catalogue_entries_status"
        ),
        sa.CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)",
            name="ck_knowledge_catalogue_entries_retired_has_reason",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_catalogue_entries"),
    )
    op.create_index("ix_knowledge_catalogue_entries_kind_status", ENTRIES, ["kind", "status"])
    op.create_table(
        VERSIONS,
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_catalogue_entry_versions_version"),
        # Unnamed: the convention's name would exceed Postgres' 63-character limit.
        sa.ForeignKeyConstraint(["entry_id"], [f"{ENTRIES}.id"]),
        sa.PrimaryKeyConstraint(
            "entry_id", "version", name="pk_knowledge_catalogue_entry_versions"
        ),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {ENTRIES} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {ENTRIES} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {VERSIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {VERSIONS} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(VERSIONS)
    op.drop_index("ix_knowledge_catalogue_entries_kind_status", ENTRIES)
    op.drop_table(ENTRIES)
