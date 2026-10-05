"""Cancelling an assessment run (Story 5.5, demo slice).

- `assessments_runs.status` gains `cancelled` (`queued | running | succeeded |
  partially_failed | failed | cancelled`).
- `assessments_tasks.status` gains `skipped` (`queued | running | succeeded | failed |
  skipped`): the tasks a cancel stopped before they finished.

Grants unchanged: `psa_app` keeps SELECT, INSERT and UPDATE of the status columns (no DELETE).

Revision ID: 0018_assessments_cancel
Revises: 0017_assessments_specialists
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_assessments_cancel"
down_revision: str | None = "0017_assessments_specialists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "assessments_runs"
TASKS = "assessments_tasks"
RUN_STATUS = "ck_assessments_runs_status"
TASK_STATUS = "ck_assessments_tasks_status"


def upgrade() -> None:
    op.drop_constraint(RUN_STATUS, RUNS, type_="check")
    op.create_check_constraint(
        RUN_STATUS,
        RUNS,
        "status IN ('queued', 'running', 'succeeded', 'partially_failed', 'failed', 'cancelled')",
    )
    op.drop_constraint(TASK_STATUS, TASKS, type_="check")
    op.create_check_constraint(
        TASK_STATUS, TASKS, "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')"
    )


def downgrade() -> None:
    # The older code has neither state: a cancelled run reads as failed and its skipped
    # tasks as failed with `model_timeout` (failed tasks need a code).
    op.execute(
        f"UPDATE {TASKS} SET status = 'failed', error_code = 'model_timeout' "
        "WHERE status = 'skipped'"
    )
    op.execute(f"UPDATE {RUNS} SET status = 'failed' WHERE status = 'cancelled'")
    op.drop_constraint(TASK_STATUS, TASKS, type_="check")
    op.create_check_constraint(
        TASK_STATUS, TASKS, "status IN ('queued', 'running', 'succeeded', 'failed')"
    )
    op.drop_constraint(RUN_STATUS, RUNS, type_="check")
    op.create_check_constraint(
        RUN_STATUS,
        RUNS,
        "status IN ('queued', 'running', 'succeeded', 'partially_failed', 'failed')",
    )
