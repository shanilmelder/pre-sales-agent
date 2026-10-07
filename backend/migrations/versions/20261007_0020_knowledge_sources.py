"""Knowledge Sources (Story 3.2).

- `knowledge_sources`: the mutable header (title, product, owner, `last_reviewed_on`,
  `status` `active | retired`, `retired_reason` set exactly when retired, `row_version`).
  `psa_app`: SELECT, INSERT, UPDATE (no DELETE).
- `knowledge_source_tags`: the Source's Integration Type tags; retagging replaces the set.
  `psa_app`: SELECT, INSERT, DELETE.
- `knowledge_source_versions`: one immutable row per uploaded file. SELECT, INSERT only.
- `knowledge_source_parses`: the parse state per version (`queued`, `parsing`, `parsed`,
  `failed`). SELECT, INSERT, UPDATE.

Revision ID: 0020_knowledge_sources
Revises: 0019_knowledge_catalogue
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_knowledge_sources"
down_revision: str | None = "0019_knowledge_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
SOURCES = "knowledge_sources"
TAGS = "knowledge_source_tags"
VERSIONS = "knowledge_source_versions"
PARSES = "knowledge_source_parses"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        SOURCES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retired_reason", sa.Text(), nullable=True),
        sa.Column("last_reviewed_on", sa.Date(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_knowledge_sources_status"),
        sa.CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)",
            name="ck_knowledge_sources_retired_has_reason",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_sources"),
    )
    op.create_index("ix_knowledge_sources_status_last_reviewed_on", SOURCES, ["status", "last_reviewed_on"])
    op.create_index("ix_knowledge_sources_owner_id", SOURCES, ["owner_id"])

    op.create_table(
        TAGS,
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], [f"{SOURCES}.id"]),
        sa.ForeignKeyConstraint(["entry_id"], ["knowledge_catalogue_entries.id"]),
        sa.PrimaryKeyConstraint("source_id", "entry_id", name="pk_knowledge_source_tags"),
    )

    op.create_table(
        VERSIONS,
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("product_version", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_source_versions_version"),
        sa.ForeignKeyConstraint(["source_id"], [f"{SOURCES}.id"]),
        sa.PrimaryKeyConstraint("source_id", "version", name="pk_knowledge_source_versions"),
    )
    op.create_index("ix_knowledge_source_versions_file_sha256", VERSIONS, ["file_sha256"])

    op.create_table(
        PARSES,
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("parser", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'parsing', 'parsed', 'failed')",
            name="ck_knowledge_source_parses_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('unreadable', 'not_supported', 'no_text', 'timeout', 'too_large_output')",
            name="ck_knowledge_source_parses_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'parsed') = (text_sha256 IS NOT NULL)",
            name="ck_knowledge_source_parses_parsed_has_text",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_knowledge_source_parses_failed_has_code",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "version"],
            [f"{VERSIONS}.source_id", f"{VERSIONS}.version"],
        ),
        sa.PrimaryKeyConstraint("source_id", "version", name="pk_knowledge_source_parses"),
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SOURCES} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {SOURCES} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {TAGS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE ON {TAGS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {VERSIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {VERSIONS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {PARSES} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {PARSES} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(PARSES)
    op.drop_index("ix_knowledge_source_versions_file_sha256", VERSIONS)
    op.drop_table(VERSIONS)
    op.drop_table(TAGS)
    op.drop_index("ix_knowledge_sources_owner_id", SOURCES)
    op.drop_index("ix_knowledge_sources_status_last_reviewed_on", SOURCES)
    op.drop_table(SOURCES)
