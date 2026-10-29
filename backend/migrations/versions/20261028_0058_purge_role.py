"""The retention purge role and its daily job (Story 10.6).

`psa_purge` is the only role that may delete Opportunity data. It is used only by the
worker's `platform.purge` job (`PSA_PURGE_DATABASE_URL`); the api and every other job connect
as `psa_app`, which keeps its existing privileges (no new DELETE grants).

- The role: created if missing, `LOGIN` with `PSA_PURGE_DB_PASSWORD` when that is set at
  migration time, otherwise `NOLOGIN` (the purge job then cannot connect and logs it). An
  existing role keeps its login unless the password is set. `ops/postgres/init/20-purge-role.sh`
  creates it the same way on a fresh volume.
- Grants: SELECT and DELETE on every per-Opportunity table (module tables and their children,
  `platform_trace_events`, `platform_model_calls`, `platform_tool_calls`, `platform_jobs`),
  INSERT on `platform_trace_events` (the `platform.purge.completed` event), SELECT and UPDATE
  on `platform_files` (reference counts), UPDATE on `opportunities_opportunities.row_version`
  only (so the purge can lock the Opportunity row with `SELECT ... FOR UPDATE` and re-check it
  is still due; it never updates it), and SELECT and DELETE on the LangGraph checkpoint
  tables in `orchestration_checkpoints`: the existing ones, and through default privileges
  those `psa_app` creates later. Nothing on identity, knowledge sources, the catalogue,
  the registry or the schedules.
- A partial index for the recent purge events (Admin > Retention).
- The daily `platform.purge` schedule (86,400 s).

Downgrade revokes the grants in this database and removes the schedule and index; the role
itself stays (roles are cluster-wide and other databases may use it).

Revision ID: 0058_purge_role
Revises: 0057_opportunities_outcome
Create Date: 2026-10-28
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058_purge_role"
down_revision: str | None = "0057_opportunities_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "psa_purge"
APP_ROLE = "psa_app"
CHECKPOINT_SCHEMA = "orchestration_checkpoints"
SCHEDULE = "platform.purge"
DAY_S = 86_400
INDEX = "ix_platform_trace_events_purge_completed"
TABLES = (
    "actuals_actuals",
    "actuals_deliveries",
    "actuals_imports",
    "assessments_assessment_finding_requirements",
    "assessments_assessment_findings",
    "assessments_assessments",
    "assessments_effort",
    "assessments_finding_evidence",
    "assessments_finding_lines",
    "assessments_finding_overrides",
    "assessments_finding_requirements",
    "assessments_finding_targets",
    "assessments_findings",
    "assessments_red_team_runs",
    "assessments_reviews",
    "conflicts_conflicts",
    "conflicts_detections",
    "conflicts_positions",
    "estimates_assumptions",
    "estimates_baselines",
    "estimates_drafts",
    "estimates_estimate_lines",
    "estimates_estimate_versions",
    "estimates_line_requirements",
    "estimates_risks",
    "gaps_answer_matches",
    "gaps_clarification_questions",
    "gaps_detections",
    "gaps_gap_history",
    "gaps_gap_requirements",
    "gaps_gaps",
    "intake_extractions",
    "intake_requirement_changes",
    "intake_requirement_evidence",
    "intake_requirement_integration_types",
    "intake_requirement_versions",
    "intake_requirements",
    "intake_source_parses",
    "intake_source_passages",
    "intake_source_versions",
    "intake_sources",
    "knowledge_research_snapshots",
    "notifications_notifications",
    "opportunities_collaborators",
    "opportunities_opportunities",
    "platform_jobs",
    "platform_model_calls",
    "platform_tool_calls",
    "platform_trace_events",
    "reviews_challenges",
    "reviews_review_decisions",
    "reviews_review_replies",
    "reviews_review_requests",
    "workflows_decisions",
    "workflows_plan_versions",
    "workflows_progress",
    "workflows_runs",
    "workflows_tasks",
)
"""Every table the purge empties (the registered steps' `tables` plus the platform's own);
`tests/test_purge.py` checks this list against the registry."""


def _role() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}
    ).scalar()
    password = os.environ.get("PSA_PURGE_DB_PASSWORD", "").strip()
    if not exists:
        op.execute(f"CREATE ROLE {ROLE} NOLOGIN")
    if password:
        statement = bind.execute(
            sa.text("SELECT format('ALTER ROLE psa_purge WITH LOGIN PASSWORD %L', :p)"),
            {"p": password},
        ).scalar_one()
        bind.exec_driver_sql(statement)


def upgrade() -> None:
    _role()
    op.execute(
        "DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO psa_purge', "
        "current_database()); END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    for table in TABLES:
        op.execute(f"GRANT SELECT, DELETE ON {table} TO {ROLE}")
    op.execute(f"GRANT INSERT ON platform_trace_events TO {ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON platform_files TO {ROLE}")
    # `SELECT ... FOR UPDATE` needs UPDATE on at least one column: the row lock only.
    op.execute(f"GRANT UPDATE (row_version) ON opportunities_opportunities TO {ROLE}")

    # LangGraph's tables, created by the worker's checkpointer as psa_app.
    op.execute(f"GRANT USAGE ON SCHEMA {CHECKPOINT_SCHEMA} TO {ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {APP_ROLE} IN SCHEMA {CHECKPOINT_SCHEMA} "
        f"GRANT SELECT, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(
        f"GRANT SELECT, DELETE ON ALL TABLES IN SCHEMA {CHECKPOINT_SCHEMA} TO {ROLE}"
    )

    op.create_index(
        INDEX,
        "platform_trace_events",
        ["occurred_at"],
        postgresql_where=sa.text("event_type = 'platform.purge.completed'"),
    )
    op.execute(
        sa.text(
            "INSERT INTO platform_schedules (name, job_type, interval_s) "
            "VALUES (:name, :name, :interval) ON CONFLICT (name) DO NOTHING"
        ).bindparams(name=SCHEDULE, interval=DAY_S)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM platform_schedules WHERE name = :name").bindparams(name=SCHEDULE)
    )
    # The older code has no purge job: open ones would only go dead.
    op.execute(
        sa.text(
            "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
            "lease_expires_at = NULL, last_error = 'Downgraded' "
            "WHERE job_type = :t AND status IN ('queued', 'running', 'failed_retrying')"
        ).bindparams(t=SCHEDULE)
    )
    op.drop_index(INDEX, table_name="platform_trace_events")
    op.execute(
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {CHECKPOINT_SCHEMA} FROM {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {APP_ROLE} IN SCHEMA {CHECKPOINT_SCHEMA} "
        f"REVOKE SELECT, DELETE ON TABLES FROM {ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA {CHECKPOINT_SCHEMA} FROM {ROLE}")
    op.execute(f"REVOKE ALL ON platform_files FROM {ROLE}")
    op.execute(f"REVOKE UPDATE (row_version) ON opportunities_opportunities FROM {ROLE}")
    for table in TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    op.execute(
        "DO $$ BEGIN EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM psa_purge', "
        "current_database()); END $$"
    )
