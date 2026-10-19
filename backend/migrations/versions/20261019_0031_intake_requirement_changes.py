"""Pending Requirement changes (Story 2.7, demo slice).

- `intake_requirement_changes`: a change extraction proposes to a human-locked Requirement,
  against its `base_version`: the proposed text, classification and passage ids, a `status`
  (`open | accepted | rejected | superseded`), the rejection `reason`, who decided and when,
  the proposing extraction, and a `row_version`. At most one `open` change per Requirement
  (`uq_intake_requirement_changes_one_open`). `psa_app`: SELECT, INSERT, UPDATE (no DELETE).

Downgrade drops the table (the older code has no pending changes).

Revision ID: 0031_intake_requirement_changes
Revises: 0030_gaps_question_sent
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_intake_requirement_changes"
down_revision: str | None = "0030_gaps_question_sent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "intake_requirement_changes"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("passage_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'accepted', 'rejected', 'superseded')",
            name="ck_intake_requirement_changes_status",
        ),
        sa.CheckConstraint(
            "classification IN ('functional', 'integration', 'data', 'security', "
            "'non_functional', 'commercial')",
            name="ck_intake_requirement_changes_classification",
        ),
        sa.CheckConstraint("base_version >= 1", name="ck_intake_requirement_changes_base_version"),
        sa.CheckConstraint(
            "(status = 'rejected') = (reason IS NOT NULL)",
            name="ck_intake_requirement_changes_rejected_has_reason",
        ),
        sa.CheckConstraint(
            "(status IN ('accepted', 'rejected')) = (decided_by IS NOT NULL) "
            "AND (decided_by IS NULL) = (decided_at IS NULL)",
            name="ck_intake_requirement_changes_decided_fields",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["intake_requirements.id"],
            name="fk_intake_requirement_changes_requirement_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["intake_extractions.id"],
            name="fk_intake_requirement_changes_extraction_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intake_requirement_changes"),
    )
    op.create_index(
        "uq_intake_requirement_changes_one_open",
        TABLE,
        ["requirement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {TABLE} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {TABLE} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("uq_intake_requirement_changes_one_open", TABLE)
    op.drop_table(TABLE)
