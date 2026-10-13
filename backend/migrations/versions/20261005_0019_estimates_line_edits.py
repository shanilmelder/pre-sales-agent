"""Editing an Estimate line's hours and role mix (Story 8.2, demo slice).

- `estimates_estimate_lines` gains `row_version` (default 1, for `If-Match`), and `edited_by`,
  `edited_at`, `edit_reason` (the person's last edit of the line: all three or none) and
  `edit_carried_from_version` (the version number a re-draft carried the edit from, null for
  an edit made on this version or a line never edited).
- `estimates_estimate_versions` gains `uncarried_edit_count` (default 0): the edited lines of
  the superseded draft that a re-draft found no matching line for.

`psa_app` gets UPDATE on only the line's edit columns (`effort_hours`, `role_mix`,
`row_version`, `edited_by`, `edited_at`, `edit_reason`, `edit_carried_from_version`); the
title, section, basis, position and version stay insert-only. Still no DELETE.

Revision ID: 0019_estimates_line_edits
Revises: 0018_assessments_cancel
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_estimates_line_edits"
down_revision: str | None = "0018_assessments_cancel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
LINES = "estimates_estimate_lines"
VERSIONS = "estimates_estimate_versions"
EDIT_COLUMNS = (
    "effort_hours, role_mix, row_version, edited_by, edited_at, edit_reason, "
    "edit_carried_from_version"
)


def upgrade() -> None:
    op.add_column(
        LINES, sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False)
    )
    op.add_column(LINES, sa.Column("edited_by", sa.Uuid(), nullable=True))
    op.add_column(LINES, sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(LINES, sa.Column("edit_reason", sa.Text(), nullable=True))
    op.add_column(LINES, sa.Column("edit_carried_from_version", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_estimates_estimate_lines_edited_has_by",
        LINES,
        "(edited_at IS NULL) = (edited_by IS NULL) AND (edited_at IS NULL) = (edit_reason IS NULL)",
    )
    op.create_check_constraint(
        "ck_estimates_estimate_lines_carried_was_edited",
        LINES,
        "edit_carried_from_version IS NULL OR edited_at IS NOT NULL",
    )
    op.add_column(
        VERSIONS,
        sa.Column(
            "uncarried_edit_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_estimates_estimate_versions_uncarried_edit_count",
        VERSIONS,
        "uncarried_edit_count >= 0",
    )

    op.execute(f"REVOKE UPDATE, DELETE ON {LINES} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {LINES} TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({EDIT_COLUMNS}) ON {LINES} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({EDIT_COLUMNS}) ON {LINES} FROM {APP_ROLE}")
    op.drop_constraint(
        "ck_estimates_estimate_versions_uncarried_edit_count", VERSIONS, type_="check"
    )
    op.drop_column(VERSIONS, "uncarried_edit_count")
    op.drop_constraint("ck_estimates_estimate_lines_carried_was_edited", LINES, type_="check")
    op.drop_constraint("ck_estimates_estimate_lines_edited_has_by", LINES, type_="check")
    for column in (
        "edit_carried_from_version",
        "edit_reason",
        "edited_at",
        "edited_by",
        "row_version",
    ):
        op.drop_column(LINES, column)
