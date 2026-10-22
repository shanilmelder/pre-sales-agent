"""Checklists (Story 3.4).

- `knowledge_checklists`: the mutable header: the published name, `domain` (`engineering |
  delivery | security | commercial | general`), products and industry, the one unpublished
  `draft` (JSONB, null when there is none), `status` `active | retired`, `retired_reason`
  set exactly when retired, `row_version`. `psa_app`: SELECT, INSERT, UPDATE (no DELETE).
- `knowledge_checklist_scope_tags`: the published scope's Integration Types; publishing
  replaces the set. `psa_app`: SELECT, INSERT, DELETE.
- `knowledge_checklist_versions`: one immutable row per published version (name, domain,
  scope snapshot, published by and at). SELECT, INSERT only.
- `knowledge_checklist_items`: the items of each published version, keyed by a stable
  `item_id` that persists across versions. SELECT, INSERT only.

Revision ID: 0036_knowledge_checklists
Revises: 0035_knowledge_chunks
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_knowledge_checklists"
down_revision: str | None = "0035_knowledge_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
CHECKLISTS = "knowledge_checklists"
TAGS = "knowledge_checklist_scope_tags"
VERSIONS = "knowledge_checklist_versions"
ITEMS = "knowledge_checklist_items"
ENTRIES = "knowledge_catalogue_entries"
DOMAINS = "domain IN ('engineering', 'delivery', 'security', 'commercial', 'general')"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        CHECKLISTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("products", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("draft", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retired_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(DOMAINS, name="ck_knowledge_checklists_domain"),
        sa.CheckConstraint(
            "status IN ('active', 'retired')", name="ck_knowledge_checklists_status"
        ),
        sa.CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)",
            name="ck_knowledge_checklists_retired_has_reason",
        ),
        sa.CheckConstraint(
            "status = 'active' OR draft IS NULL",
            name="ck_knowledge_checklists_retired_has_no_draft",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_checklists"),
    )
    op.create_index("ix_knowledge_checklists_status", CHECKLISTS, ["status"])

    op.create_table(
        TAGS,
        sa.Column("checklist_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["checklist_id"], [f"{CHECKLISTS}.id"]),
        sa.ForeignKeyConstraint(["entry_id"], [f"{ENTRIES}.id"]),
        sa.PrimaryKeyConstraint(
            "checklist_id", "entry_id", name="pk_knowledge_checklist_scope_tags"
        ),
    )

    op.create_table(
        VERSIONS,
        sa.Column("checklist_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_checklist_versions_version"),
        sa.CheckConstraint(DOMAINS, name="ck_knowledge_checklist_versions_domain"),
        sa.ForeignKeyConstraint(["checklist_id"], [f"{CHECKLISTS}.id"]),
        sa.PrimaryKeyConstraint("checklist_id", "version", name="pk_knowledge_checklist_versions"),
    )

    op.create_table(
        ITEMS,
        sa.Column("checklist_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=False),
        sa.Column("affected_entry_id", sa.Uuid(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_checklist_items_ordinal"),
        sa.CheckConstraint(
            "kind IN ('question', 'risk')", name="ck_knowledge_checklist_items_kind"
        ),
        sa.CheckConstraint(
            "impact IN ('high', 'medium', 'low')", name="ck_knowledge_checklist_items_impact"
        ),
        sa.ForeignKeyConstraint(
            ["checklist_id", "version"], [f"{VERSIONS}.checklist_id", f"{VERSIONS}.version"]
        ),
        sa.ForeignKeyConstraint(["affected_entry_id"], [f"{ENTRIES}.id"]),
        sa.PrimaryKeyConstraint(
            "checklist_id", "version", "item_id", name="pk_knowledge_checklist_items"
        ),
        sa.UniqueConstraint(
            "checklist_id",
            "version",
            "ordinal",
            name="uq_knowledge_checklist_items_checklist_id_version_ordinal",
        ),
    )
    op.create_index("ix_knowledge_checklist_items_item_id", ITEMS, ["item_id"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {CHECKLISTS} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {CHECKLISTS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {TAGS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE ON {TAGS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {VERSIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {VERSIONS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {ITEMS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {ITEMS} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_knowledge_checklist_items_item_id", ITEMS)
    op.drop_table(ITEMS)
    op.drop_table(VERSIONS)
    op.drop_table(TAGS)
    op.drop_index("ix_knowledge_checklists_status", CHECKLISTS)
    op.drop_table(CHECKLISTS)
