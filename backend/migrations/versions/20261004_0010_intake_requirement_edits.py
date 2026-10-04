"""Human edits and confirmation of Requirements (Story 2.6).

- `intake_requirement_versions`: every version of a Requirement's text and classification,
  immutable (`psa_app`: SELECT, INSERT only). `created_by` is the actor id
  (`intake_agent@<semver>` or a user's id). Version 1 of every existing Requirement is
  backfilled from the Requirement itself, attributed to the agent that completed its
  extraction (`intake_agent` when that trace event can't be found).
- `intake_requirements.confirmed_at` / `confirmed_by`: who confirmed it and when (both or
  neither).

Revision ID: 0010_intake_requirement_edits
Revises: 0009_intake_requirements
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_intake_requirement_edits"
down_revision: str | None = "0009_intake_requirements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"


def upgrade() -> None:
    op.add_column(
        "intake_requirements",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("intake_requirements", sa.Column("confirmed_by", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_intake_requirements_confirmed_has_by",
        "intake_requirements",
        "(confirmed_at IS NULL) = (confirmed_by IS NULL)",
    )

    op.create_table(
        "intake_requirement_versions",
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name="ck_intake_requirement_versions_version"),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["intake_requirements.id"],
            name="fk_intake_requirement_versions_requirement_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("requirement_id", "version", name="pk_intake_requirement_versions"),
    )

    # Before this revision every Requirement is at version 1, written by extraction.
    op.execute(
        """
        INSERT INTO intake_requirement_versions
            (requirement_id, version, text, classification, created_by, created_at)
        SELECT r.id, r.version, r.text, r.classification,
               COALESCE(
                   (SELECT t.actor_id FROM platform_trace_events t
                     WHERE t.subject_type = 'intake.extraction'
                       AND t.subject_id = r.extraction_id
                       AND t.event_type = 'intake.extraction.completed'
                     ORDER BY t.occurred_at DESC LIMIT 1),
                   'intake_agent'),
               r.created_at
          FROM intake_requirements r
        """
    )

    op.execute(f"GRANT SELECT, INSERT ON intake_requirement_versions TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON intake_requirement_versions FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("intake_requirement_versions")
    op.drop_constraint(
        "ck_intake_requirements_confirmed_has_by", "intake_requirements", type_="check"
    )
    op.drop_column("intake_requirements", "confirmed_by")
    op.drop_column("intake_requirements", "confirmed_at")
