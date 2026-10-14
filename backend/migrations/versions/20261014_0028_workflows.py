"""The workflows module, durable LangGraph execution and live progress (Story 5.2).

- `assessments_runs` → `workflows_runs` and `assessments_tasks` → `workflows_tasks`, renamed
  in place (ids, history and grants kept), with their primary keys, checks, foreign keys,
  unique constraint and index renamed to match.
- `workflows_runs.plan_version` (int, default 1) and `workflows_tasks.requires` (uuid[],
  default empty: the ids of the run's tasks a task waits for). `psa_app` cannot update
  either.
- `assessments_assessments.run_id` loses its foreign key: a plain id of a Workflow Run,
  owned by another module (AD-2), as `estimates_estimate_versions.source_run_id`.
- `workflows_progress`: non-audit progress rows (a run queued or ended, a task started or
  ended), ids and a summary of Agent ids and statuses only. `psa_app`: SELECT, INSERT,
  DELETE (the daily prune), no UPDATE.
- `platform_schedules`: recurring jobs (name, job type, interval, next run), seeded with the
  daily `workflows.prune_progress`. `psa_app`: SELECT and UPDATE of `next_run_at` and
  `last_enqueued_at` only.
- Schema `orchestration_checkpoints` for the LangGraph checkpointer. `psa_app` cannot create
  schemas, so it is created here and `psa_app` gets USAGE and CREATE on it: the worker's
  `AsyncPostgresSaver.setup()` creates the library's tables there.
- Jobs of type `assessments.run_assessment` become `workflows.execute` (same payload).

Downgrade restores the old tables, names, foreign key and job type, and drops the new
tables and the checkpoint schema (with its checkpoints).

Revision ID: 0028_workflows
Revises: 0027_registry_eval_results
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_workflows"
down_revision: str | None = "0027_registry_eval_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
SCHEMA = "orchestration_checkpoints"
OLD_JOB = "assessments.run_assessment"
NEW_JOB = "workflows.execute"
PRUNE_JOB = "workflows.prune_progress"
PROGRESS_EVENTS = (
    "workflows.run.queued",
    "workflows.task.started",
    "workflows.task.ended",
    "workflows.run.ended",
)

# (old constraint name, new constraint name), with the tables already renamed. The earlier
# migrations' check constraints carry the naming convention's prefix twice.
RUN_CONSTRAINTS = (
    ("pk_assessments_runs", "pk_workflows_runs"),
    ("ck_assessments_runs_ck_assessments_runs_status", "ck_workflows_runs_status"),
)
TASK_CONSTRAINTS = (
    ("pk_assessments_tasks", "pk_workflows_tasks"),
    ("ck_assessments_tasks_ck_assessments_tasks_agent", "ck_workflows_tasks_agent"),
    ("ck_assessments_tasks_ck_assessments_tasks_status", "ck_workflows_tasks_status"),
    ("ck_assessments_tasks_ck_assessments_tasks_error_code", "ck_workflows_tasks_error_code"),
    (
        "ck_assessments_tasks_ck_assessments_tasks_failed_has_code",
        "ck_workflows_tasks_failed_has_code",
    ),
    ("ck_assessments_tasks_ck_assessments_tasks_skip_reason", "ck_workflows_tasks_skip_reason"),
    ("fk_assessments_tasks_run_id", "fk_workflows_tasks_run_id"),
    ("fk_assessments_tasks_config_version_id", "fk_workflows_tasks_config_version_id"),
    ("uq_assessments_tasks_run_id_agent", "uq_workflows_tasks_run_id_agent"),
)
RUN_INDEX = (
    "ix_assessments_runs_opportunity_id_created_at",
    "ix_workflows_runs_opportunity_id_created_at",
)


def _rename_constraints(table: str, pairs: Sequence[tuple[str, str]], *, back: bool) -> None:
    for old, new in pairs:
        src, dst = (new, old) if back else (old, new)
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {src} TO {dst}")


def upgrade() -> None:
    # --- runs and tasks move to workflows ---------------------------------------------------
    op.drop_constraint(
        "fk_assessments_assessments_run_id", "assessments_assessments", type_="foreignkey"
    )
    op.rename_table("assessments_runs", "workflows_runs")
    op.rename_table("assessments_tasks", "workflows_tasks")
    _rename_constraints("workflows_runs", RUN_CONSTRAINTS, back=False)
    _rename_constraints("workflows_tasks", TASK_CONSTRAINTS, back=False)
    op.execute(f"ALTER INDEX {RUN_INDEX[0]} RENAME TO {RUN_INDEX[1]}")

    op.add_column(
        "workflows_runs",
        sa.Column("plan_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_workflows_runs_plan_version"), "workflows_runs", "plan_version >= 1"
    )
    op.add_column(
        "workflows_tasks",
        sa.Column(
            "requires",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )

    # --- progress ---------------------------------------------------------------------------
    op.create_table(
        "workflows_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("subject_version", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN (" + ", ".join(f"'{e}'" for e in PROGRESS_EVENTS) + ")",
            name=op.f("ck_workflows_progress_event_type"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflows_runs.id"],
            name="fk_workflows_progress_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflows_progress"),
    )
    op.create_index(
        "ix_workflows_progress_opportunity_id_id", "workflows_progress", ["opportunity_id", "id"]
    )
    op.create_index("ix_workflows_progress_occurred_at", "workflows_progress", ["occurred_at"])
    op.execute(f"GRANT SELECT, INSERT, DELETE ON workflows_progress TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, TRUNCATE ON workflows_progress FROM {APP_ROLE}")

    # --- schedules --------------------------------------------------------------------------
    schedules = op.create_table(
        "platform_schedules",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("interval_s > 0", name=op.f("ck_platform_schedules_interval_s")),
        sa.PrimaryKeyConstraint("name", name="pk_platform_schedules"),
    )
    op.bulk_insert(schedules, [{"name": PRUNE_JOB, "job_type": PRUNE_JOB, "interval_s": 86400}])
    op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform_schedules FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT ON platform_schedules TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (next_run_at, last_enqueued_at) ON platform_schedules TO {APP_ROLE}")

    # --- the checkpointer's schema ----------------------------------------------------------
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA {SCHEMA} TO {APP_ROLE}")

    # --- queued jobs keep running under the new job type ------------------------------------
    op.execute(
        sa.text("UPDATE platform_jobs SET job_type = :new WHERE job_type = :old").bindparams(
            new=NEW_JOB, old=OLD_JOB
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE platform_jobs SET job_type = :old WHERE job_type = :new").bindparams(
            new=NEW_JOB, old=OLD_JOB
        )
    )
    # The older code has no prune job: open ones would only go dead.
    op.execute(
        sa.text(
            "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
            "lease_expires_at = NULL, last_error = 'Downgraded' "
            "WHERE job_type = :t AND status IN ('queued', 'running', 'failed_retrying')"
        ).bindparams(t=PRUNE_JOB)
    )
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    op.drop_table("platform_schedules")
    op.drop_index("ix_workflows_progress_occurred_at", table_name="workflows_progress")
    op.drop_index("ix_workflows_progress_opportunity_id_id", table_name="workflows_progress")
    op.drop_table("workflows_progress")

    # A task that waited on others ran as soon as the older code started it: nothing to keep.
    op.drop_column("workflows_tasks", "requires")
    op.drop_constraint(op.f("ck_workflows_runs_plan_version"), "workflows_runs", type_="check")
    op.drop_column("workflows_runs", "plan_version")
    op.execute(f"ALTER INDEX {RUN_INDEX[1]} RENAME TO {RUN_INDEX[0]}")
    _rename_constraints("workflows_tasks", TASK_CONSTRAINTS, back=True)
    _rename_constraints("workflows_runs", RUN_CONSTRAINTS, back=True)
    op.rename_table("workflows_tasks", "assessments_tasks")
    op.rename_table("workflows_runs", "assessments_runs")
    op.create_foreign_key(
        "fk_assessments_assessments_run_id",
        "assessments_assessments",
        "assessments_runs",
        ["run_id"],
        ["id"],
    )
