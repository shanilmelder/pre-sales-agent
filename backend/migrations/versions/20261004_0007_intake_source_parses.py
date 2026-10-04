"""Source parse state (Story 2.2 Part B).

`intake_source_parses` holds one row per Source version: `queued`, `parsing`, `parsed` (with
the extracted-text blob's `text_sha256`, `char_count` and `parser`) or `failed` (with an
`error_code`). Version rows are immutable, so the state lives here. `psa_app` gets SELECT,
INSERT and UPDATE (rows go only with their version, by cascade), not DELETE.

Backfill: every existing version gets a `queued` row and an `intake.parse_source` job
(background priority), so Sources added before this release are parsed too.

Revision ID: 0007_intake_source_parses
Revises: 0006_platform_jobs
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_intake_source_parses"
down_revision: str | None = "0006_platform_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
JOB_TYPE = "intake.parse_source"


def upgrade() -> None:
    op.create_table(
        "intake_source_parses",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("parser", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'parsing', 'parsed', 'failed')",
            name="ck_intake_source_parses_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('unreadable', 'not_supported', 'no_text', 'timeout', 'too_large_output')",
            name="ck_intake_source_parses_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'parsed') = (text_sha256 IS NOT NULL)",
            name="ck_intake_source_parses_parsed_has_text",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_intake_source_parses_failed_has_code",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "version"],
            ["intake_source_versions.source_id", "intake_source_versions.version"],
            name="fk_intake_source_parses_source_id_intake_source_versions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", "version", name="pk_intake_source_parses"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON intake_source_parses TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON intake_source_parses FROM {APP_ROLE}")

    op.execute(
        "INSERT INTO intake_source_parses (source_id, version, status, row_version) "
        "SELECT source_id, version, 'queued', 1 FROM intake_source_versions"
    )
    op.execute(
        "INSERT INTO platform_jobs (id, job_type, payload, priority, status, attempts, "
        "run_after, opportunity_id) "
        f"SELECT uuidv7(), '{JOB_TYPE}', "
        "jsonb_build_object('source_id', v.source_id::text, 'version', v.version), "
        "1, 'queued', 0, now(), s.opportunity_id "
        "FROM intake_source_versions v JOIN intake_sources s ON s.id = v.source_id "
        "ORDER BY v.uploaded_at, v.source_id, v.version"
    )


def downgrade() -> None:
    # Jobs for a type this revision's code no longer has would only go dead.
    op.execute(
        f"UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
        f"lease_expires_at = NULL, last_error = 'Downgraded' "
        f"WHERE job_type = '{JOB_TYPE}' AND status IN ('queued', 'running', 'failed_retrying')"
    )
    op.drop_table("intake_source_parses")
