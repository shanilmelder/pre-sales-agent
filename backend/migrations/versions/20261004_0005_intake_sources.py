"""File metadata and Opportunity Sources (Story 2.1).

`platform_files` holds one row per stored blob (content-addressed by SHA-256) with its
reference count. `intake_sources` and `intake_source_versions` are the Sources and their
immutable versions; `opportunity_id`, `created_by` and `uploaded_by` hold other modules'
ids with no foreign key (AD-2). `psa_app` gets SELECT, INSERT, UPDATE, DELETE on the new
tables through the default privileges set in 0002.

Revision ID: 0005_intake_sources
Revises: 0004_opportunities
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_intake_sources"
down_revision: str | None = "0004_opportunities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_files",
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("ref_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_platform_files_size_bytes"),
        sa.CheckConstraint("ref_count >= 0", name="ck_platform_files_ref_count"),
        sa.PrimaryKeyConstraint("sha256", name="pk_platform_files"),
    )
    op.create_table(
        "intake_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_intake_sources"),
    )
    op.create_index(
        "ix_intake_sources_opportunity_id_created_at",
        "intake_sources",
        ["opportunity_id", "created_at"],
    )
    op.create_table(
        "intake_source_versions",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["intake_sources.id"],
            name="fk_intake_source_versions_source_id_intake_sources",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", "version", name="pk_intake_source_versions"),
    )
    op.create_index(
        "ix_intake_source_versions_file_sha256", "intake_source_versions", ["file_sha256"]
    )


def downgrade() -> None:
    op.drop_index("ix_intake_source_versions_file_sha256", table_name="intake_source_versions")
    op.drop_table("intake_source_versions")
    op.drop_index("ix_intake_sources_opportunity_id_created_at", table_name="intake_sources")
    op.drop_table("intake_sources")
    op.drop_table("platform_files")
