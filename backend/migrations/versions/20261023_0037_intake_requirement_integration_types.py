"""Requirement Integration Type tags (Story 4.1).

- `intake_requirement_integration_types`: the human-owned set of catalogue Integration Types
  a Requirement is tagged with (`requirement_id`, `entry_id`, `tagged_by`, `tagged_at`, PK on
  both ids). `entry_id` is a knowledge catalogue entry, held without a foreign key (AD-2).
  Saving the set replaces it: `psa_app` has SELECT, INSERT and DELETE, no UPDATE.
  Extraction never reads or writes it, and it is not versioned with the Requirement.

Revision ID: 0037_requirement_tags
Revises: 0036_knowledge_checklists
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_requirement_tags"
down_revision: str | None = "0036_knowledge_checklists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "intake_requirement_integration_types"
INDEX = "ix_intake_requirement_integration_types_entry_id"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("tagged_by", sa.Uuid(), nullable=False),
        sa.Column(
            "tagged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["intake_requirements.id"],
            ondelete="CASCADE",
            name="fk_intake_requirement_integration_types_requirement_id",
        ),
        sa.PrimaryKeyConstraint(
            "requirement_id", "entry_id", name="pk_intake_requirement_integration_types"
        ),
    )
    op.create_index(INDEX, TABLE, ["entry_id"])
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {TABLE} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE ON {TABLE} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(INDEX, TABLE)
    op.drop_table(TABLE)
