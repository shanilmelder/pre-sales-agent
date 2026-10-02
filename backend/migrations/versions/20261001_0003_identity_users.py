"""identity users and roles (Story 1.4 Part B).

`psa_app` gets SELECT, INSERT, UPDATE, DELETE on both tables through the default
privileges set in 0002.

Revision ID: 0003_identity_users
Revises: 0002_platform_trace
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_identity_users"
down_revision: str | None = "0002_platform_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auth0_sub", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_users"),
        sa.UniqueConstraint("auth0_sub", name="uq_identity_users_auth0_sub"),
    )
    op.create_table(
        "identity_user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
            name="fk_identity_user_roles_user_id_identity_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role", name="pk_identity_user_roles"),
    )


def downgrade() -> None:
    op.drop_table("identity_user_roles")
    op.drop_table("identity_users")
