"""Opportunities and collaborators (Story 1.7).

`owner_id` and `user_id` hold identity user ids with no foreign key across modules (AD-2).
Status is derived by a query and never stored (AD-26). `psa_app` gets SELECT, INSERT,
UPDATE, DELETE on both tables through the default privileges set in 0002.

Revision ID: 0004_opportunities
Revises: 0003_identity_users
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_opportunities"
down_revision: str | None = "0003_identity_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opportunities_opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("products", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("industry", sa.Text(), nullable=False),
        sa.Column("target_proposal_date", sa.Date(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_opportunities_opportunities"),
    )
    op.create_index(
        "ix_opportunities_opportunities_owner_id", "opportunities_opportunities", ["owner_id"]
    )
    op.create_index(
        "ix_opportunities_opportunities_created_at_id",
        "opportunities_opportunities",
        ["created_at", "id"],
    )
    op.create_table(
        "opportunities_collaborators",
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities_opportunities.id"],
            name="fk_opportunities_collaborators_opportunity_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "opportunity_id", "user_id", name="pk_opportunities_collaborators"
        ),
    )
    op.create_index(
        "ix_opportunities_collaborators_user_id", "opportunities_collaborators", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_opportunities_collaborators_user_id", table_name="opportunities_collaborators")
    op.drop_table("opportunities_collaborators")
    op.drop_index(
        "ix_opportunities_opportunities_created_at_id", table_name="opportunities_opportunities"
    )
    op.drop_index(
        "ix_opportunities_opportunities_owner_id", table_name="opportunities_opportunities"
    )
    op.drop_table("opportunities_opportunities")
