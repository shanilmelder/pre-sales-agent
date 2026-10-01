"""Platform trace table and the least-privileged application role's grants (AD-12).

The `psa_app` login role is created outside migrations (ops/postgres/init/10-app-role.sh,
or the CI setup step). It gets SELECT and INSERT only on the trace table, so trace rows
can't be changed or deleted by the app. Default privileges give it SELECT, INSERT, UPDATE
and DELETE on tables that later migrations create (they run as the same owner role).

Revision ID: 0002_platform_trace
Revises: 0001_baseline
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_platform_trace"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'role {APP_ROLE} does not exist; it is created by '
                    'ops/postgres/init/10-app-role.sh (recreate the volume with '
                    '"docker compose down -v")';
            END IF;
            IF current_user = '{APP_ROLE}' THEN
                RAISE EXCEPTION 'migrations must run as the schema owner, not {APP_ROLE}; '
                    'set PSA_MIGRATIONS_DATABASE_URL to the owner role''s URL';
            END IF;
        END $$
        """
    )
    op.create_table(
        "platform_trace_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("subject_version", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'agent', 'system')",
            name="ck_platform_trace_events_actor_type",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_trace_events"),
    )
    op.create_index(
        "ix_platform_trace_events_opportunity_id_occurred_at",
        "platform_trace_events",
        ["opportunity_id", "occurred_at"],
    )
    op.create_index(
        "ix_platform_trace_events_subject_type_subject_id",
        "platform_trace_events",
        ["subject_type", "subject_id"],
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON platform_trace_events TO {APP_ROLE}")
    # Default privileges apply only to objects created after this statement, so it must come
    # after create_table: the trace table must not pick up UPDATE/DELETE.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.drop_index(
        "ix_platform_trace_events_subject_type_subject_id", table_name="platform_trace_events"
    )
    op.drop_index(
        "ix_platform_trace_events_opportunity_id_occurred_at", table_name="platform_trace_events"
    )
    op.drop_table("platform_trace_events")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
