"""Pause and resume: decisions a run waits on, and every plan version (Story 5.5).

- `workflows_runs.status` gains `waiting_for_human`; `workflows_progress.event_type` gains
  `workflows.run.waiting_for_human`.
- `workflows_decisions`: a decision a run waits on (`plan_escalation` for a task whose
  Agent is not active): run, task, kind, `open|resolved|cancelled`, the choice
  (`continue_without|replan`), a payload of ids and codes, who resolved it and when, and
  `row_version`; unique per (run, task, kind). `psa_app`: SELECT, INSERT, and UPDATE of
  `status`, `choice`, `resolved_by`, `resolved_at` and `row_version` only.
- `workflows_plan_versions`: every version of a run's plan (FR-15): per task its Agent and
  pinned config version, who made it and when; unique per (run, version). `psa_app`:
  SELECT and INSERT only. Existing runs get their v1 backfilled from their tasks (made by
  whoever the run's first `assessments.assessment_run.started` event names, else the
  system).
- A Re-plan re-pins a task and bumps the run's plan version, so `psa_app` may now UPDATE
  `workflows_tasks.config_version_id` and `workflows_runs.plan_version`.

Downgrade: waiting runs become `failed` (their unfinished tasks `failed` /
`model_timeout`), open `workflows.resume` jobs go dead, the waiting progress rows are
deleted, and the new tables, values and grants are dropped.

Revision ID: 0040_workflows_decisions
Revises: 0039_tool_gateway
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_workflows_decisions"
down_revision: str | None = "0039_tool_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
DECISIONS = "workflows_decisions"
PLANS = "workflows_plan_versions"
RESUME_JOB = "workflows.resume"
WAITING_EVENT = "workflows.run.waiting_for_human"
OLD_RUN_STATUSES = ("queued", "running", "succeeded", "partially_failed", "failed", "cancelled")
NEW_RUN_STATUSES = (*OLD_RUN_STATUSES, "waiting_for_human")
OLD_PROGRESS_EVENTS = (
    "workflows.run.queued",
    "workflows.task.started",
    "workflows.task.ended",
    "workflows.run.ended",
)
NEW_PROGRESS_EVENTS = (*OLD_PROGRESS_EVENTS, WAITING_EVENT)


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _checks(run_statuses: Sequence[str], events: Sequence[str]) -> None:
    runs, progress = op.f("ck_workflows_runs_status"), op.f("ck_workflows_progress_event_type")
    op.drop_constraint(runs, "workflows_runs", type_="check")
    op.create_check_constraint(runs, "workflows_runs", f"status IN {_in(run_statuses)}")
    op.drop_constraint(progress, "workflows_progress", type_="check")
    op.create_check_constraint(progress, "workflows_progress", f"event_type IN {_in(events)}")


def upgrade() -> None:
    _checks(NEW_RUN_STATUSES, NEW_PROGRESS_EVENTS)

    op.create_table(
        DECISIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("choice", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("kind IN ('plan_escalation')", name=op.f("ck_workflows_decisions_kind")),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'cancelled')",
            name=op.f("ck_workflows_decisions_status"),
        ),
        sa.CheckConstraint(
            "choice IS NULL OR choice IN ('continue_without', 'replan')",
            name=op.f("ck_workflows_decisions_choice"),
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (choice IS NOT NULL AND resolved_at IS NOT NULL)",
            name=op.f("ck_workflows_decisions_resolved_has_choice"),
        ),
        sa.CheckConstraint("row_version >= 1", name=op.f("ck_workflows_decisions_row_version")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflows_runs.id"],
            name="fk_workflows_decisions_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["workflows_tasks.id"],
            name="fk_workflows_decisions_task_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflows_decisions"),
        sa.UniqueConstraint(
            "run_id", "task_id", "kind", name="uq_workflows_decisions_run_id_task_id_kind"
        ),
    )
    op.execute(f"GRANT SELECT, INSERT ON {DECISIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {DECISIONS} FROM {APP_ROLE}")
    op.execute(
        f"GRANT UPDATE (status, choice, resolved_by, resolved_at, row_version) "
        f"ON {DECISIONS} TO {APP_ROLE}"
    )

    op.create_table(
        PLANS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tasks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_type", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflows_plan_versions_version")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflows_runs.id"],
            name="fk_workflows_plan_versions_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflows_plan_versions"),
        sa.UniqueConstraint("run_id", "version", name="uq_workflows_plan_versions_run_id_version"),
    )
    op.execute(f"GRANT SELECT, INSERT ON {PLANS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {PLANS} FROM {APP_ROLE}")
    # Every existing run gets its v1 from its tasks (as they are now: nothing re-pinned them).
    op.execute(
        f"""
        INSERT INTO {PLANS} (id, run_id, version, tasks, created_by_type, created_by, created_at)
        SELECT gen_random_uuid(), r.id, 1,
               jsonb_agg(
                   jsonb_build_object(
                       'task_id', t.id::text,
                       'agent', t.agent,
                       'config_version_id', t.config_version_id::text
                   ) ORDER BY t.id
               ),
               coalesce(e.actor_type, 'system'),
               coalesce(e.actor_id, 'workflows.execute'),
               r.created_at
        FROM workflows_runs r
        JOIN workflows_tasks t ON t.run_id = r.id
        LEFT JOIN LATERAL (
            SELECT actor_type, actor_id FROM platform_trace_events
            WHERE subject_id = r.id AND event_type = 'assessments.assessment_run.started'
            ORDER BY occurred_at, id
            LIMIT 1
        ) e ON true
        GROUP BY r.id, r.created_at, e.actor_type, e.actor_id
        """  # noqa: S608 - constant table names only
    )

    op.execute(f"GRANT UPDATE (plan_version) ON workflows_runs TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (config_version_id) ON workflows_tasks TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (config_version_id) ON workflows_tasks FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE (plan_version) ON workflows_runs FROM {APP_ROLE}")
    # The older code can't resume a waiting run: it fails, as a lost run would.
    op.execute(
        "UPDATE workflows_tasks SET status = 'failed', error_code = 'model_timeout', "
        "skip_reason = NULL WHERE status IN ('queued', 'running') AND run_id IN "
        "(SELECT id FROM workflows_runs WHERE status = 'waiting_for_human')"
    )
    op.execute(
        "UPDATE workflows_runs SET status = 'failed', finished_at = now() "
        "WHERE status = 'waiting_for_human'"
    )
    op.execute(
        sa.text(
            "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
            "lease_expires_at = NULL, last_error = 'Downgraded' "
            "WHERE job_type = :t AND status IN ('queued', 'running', 'failed_retrying')"
        ).bindparams(t=RESUME_JOB)
    )
    op.execute(
        sa.text("DELETE FROM workflows_progress WHERE event_type = :e").bindparams(e=WAITING_EVENT)
    )
    op.drop_table(PLANS)
    op.drop_table(DECISIONS)
    _checks(OLD_RUN_STATUSES, OLD_PROGRESS_EVENTS)
