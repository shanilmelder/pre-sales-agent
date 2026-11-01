"""Challenge reassessment versions (Story 9.6).

- `estimates_estimate_versions.source` gains `challenge` (a version a Challenge's run built;
  it has a `source_run_id` like one from the Assessments), plus `idempotency_key` (the
  `node:<run>:<task>:<attempt>` key of the node that wrote it) and a unique partial index on
  `source_run_id` where `source = 'challenge'`, so a replayed node can't store a second
  version for its run.
- `notifications_notifications.kind` gains `challenge_completed` and `challenge_failed`.
- `reviews_challenges.new_version_id`: the Estimate Version a completed Challenge created.
- `workflows_tasks`: `agent` gains the non-agent nodes `conflict_detection` and
  `new_version`, which pin no config version (`config_version_id` becomes nullable, and is
  null exactly for them); `error_code` gains `estimate_changed`.
- `workflows_plan_versions.pins`: what a plan was made against (the active Requirements and
  Sources at their versions, the latest Estimate Version number); null for older plans.

The downgrade removes the new Inbox items and the non-agent tasks (also from the plan JSON),
and relabels challenge versions as built from the Assessments (they keep their run).

Revision ID: 0059_challenge_versions
Revises: 0058_purge_role
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059_challenge_versions"
down_revision: str | None = "0058_purge_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "estimates_estimate_versions"
SOURCE = "ck_estimates_estimate_versions_source"
SOURCE_HAS_RUN = "ck_estimates_estimate_versions_source_has_run"
CHALLENGE_RUN_INDEX = "uq_estimates_estimate_versions_challenge_run"
NOTIFICATIONS = "notifications_notifications"
KIND = "ck_notifications_notifications_kind"
CHALLENGES = "reviews_challenges"
NEW_VERSION_CHECK = "ck_reviews_challenges_new_version_when_completed"
TASKS = "workflows_tasks"
AGENT = "ck_workflows_tasks_agent"
ERROR_CODE = "ck_workflows_tasks_error_code"
PINNED = "ck_workflows_tasks_config_version_pinned"
PLANS = "workflows_plan_versions"
NEW_VERSION_INDEX = "ix_reviews_challenges_new_version_id"
NODES = "('conflict_detection', 'new_version')"
STRIP_NODES = f"""
UPDATE {PLANS} AS p SET tasks = (
    SELECT coalesce(jsonb_agg(
        CASE WHEN t ? 'requires' THEN jsonb_set(cleaned, '{{requires}}', coalesce((
            SELECT jsonb_agg(r ORDER BY i) FROM jsonb_array_elements(t -> 'requires')
                WITH ORDINALITY AS rq(r, i)
            WHERE NOT (r #>> '{{}}') = ANY (dropped)), '[]'::jsonb))
        ELSE cleaned END
        ORDER BY n), '[]'::jsonb)
    FROM jsonb_array_elements(p.tasks) WITH ORDINALITY AS e(t, n),
        LATERAL (SELECT array(
            SELECT d ->> 'task_id' FROM jsonb_array_elements(p.tasks) AS x(d)
            WHERE d ->> 'agent' IN {NODES}) AS dropped) AS ds,
        LATERAL (SELECT CASE WHEN t ? 'after' THEN jsonb_set(t, '{{after}}', coalesce((
            SELECT jsonb_agg(a ORDER BY i) FROM jsonb_array_elements(t -> 'after')
                WITH ORDINALITY AS af(a, i)
            WHERE NOT (a #>> '{{}}') = ANY (dropped)), '[]'::jsonb))
            ELSE t END AS cleaned) AS c
    WHERE NOT (t ->> 'agent') IN {NODES}
)
WHERE CASE WHEN jsonb_typeof(p.tasks) = 'array' THEN EXISTS (
    SELECT 1 FROM jsonb_array_elements(p.tasks) AS y(z) WHERE z ->> 'agent' IN {NODES}
) ELSE false END
"""

OLD_KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated', 'review_outcome', 'review_replied', 'challenge_raised', "
    "'challenge_declined')"
)
NEW_KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated', 'review_outcome', 'review_replied', 'challenge_raised', "
    "'challenge_declined', 'challenge_completed', 'challenge_failed')"
)
OLD_AGENTS = "('engineering_agent', 'pm_agent', 'security_agent', 'critic_agent')"
NEW_AGENTS = (
    "('engineering_agent', 'pm_agent', 'security_agent', 'critic_agent', "
    "'conflict_detection', 'new_version')"
)
OLD_CODES = "('model_unavailable', 'model_timeout', 'output_invalid')"
NEW_CODES = "('model_unavailable', 'model_timeout', 'output_invalid', 'estimate_changed')"


def _replace_check(table: str, name: str, condition: str) -> None:
    """Through the naming convention (the name it gave these checks when created)."""
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def _replace_task_check(name: str, condition: str) -> None:
    """`workflows_tasks`' checks carry their literal names (renamed in place by 0028)."""
    op.execute(f"ALTER TABLE {TASKS} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE {TASKS} ADD CONSTRAINT {name} CHECK ({condition})")


def upgrade() -> None:
    _replace_check(VERSIONS, SOURCE, "source IN ('model', 'assessments', 'challenge')")
    _replace_check(
        VERSIONS,
        SOURCE_HAS_RUN,
        "(source IN ('assessments', 'challenge')) = (source_run_id IS NOT NULL)",
    )
    op.add_column(VERSIONS, sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_index(
        CHALLENGE_RUN_INDEX,
        VERSIONS,
        ["source_run_id"],
        unique=True,
        postgresql_where=sa.text("source = 'challenge'"),
    )

    _replace_check(NOTIFICATIONS, KIND, f"kind IN {NEW_KINDS}")

    op.add_column(CHALLENGES, sa.Column("new_version_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        NEW_VERSION_CHECK, CHALLENGES, "new_version_id IS NULL OR status = 'completed'"
    )
    op.create_index(
        NEW_VERSION_INDEX,
        CHALLENGES,
        ["new_version_id"],
        postgresql_where=sa.text("new_version_id IS NOT NULL"),
    )

    _replace_task_check(AGENT, f"agent IN {NEW_AGENTS}")
    _replace_task_check(ERROR_CODE, f"error_code IS NULL OR error_code IN {NEW_CODES}")
    op.alter_column(TASKS, "config_version_id", existing_type=sa.Uuid(), nullable=True)
    op.execute(
        f"ALTER TABLE {TASKS} ADD CONSTRAINT {PINNED} CHECK "
        "((config_version_id IS NULL) = (agent IN ('conflict_detection', 'new_version')))"
    )

    op.add_column(PLANS, sa.Column("pins", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column(PLANS, "pins")
    # Older code reads every plan task's config version: drop the non-agent nodes and their
    # ids from the other tasks' `after` and `requires`.
    op.execute(STRIP_NODES)

    # The older code knows no non-agent node (their decisions and progress rows go with them).
    op.execute(f"DELETE FROM {TASKS} WHERE config_version_id IS NULL")  # noqa: S608 - constants
    op.execute(f"ALTER TABLE {TASKS} DROP CONSTRAINT {PINNED}")
    op.alter_column(TASKS, "config_version_id", existing_type=sa.Uuid(), nullable=False)
    op.execute(
        f"UPDATE {TASKS} SET status = 'failed', error_code = 'model_unavailable' "  # noqa: S608
        "WHERE error_code = 'estimate_changed'"
    )
    _replace_task_check(ERROR_CODE, f"error_code IS NULL OR error_code IN {OLD_CODES}")
    _replace_task_check(AGENT, f"agent IN {OLD_AGENTS}")

    op.drop_index(NEW_VERSION_INDEX, CHALLENGES)
    op.drop_constraint(NEW_VERSION_CHECK, CHALLENGES, type_="check")
    op.drop_column(CHALLENGES, "new_version_id")

    op.execute(
        f"DELETE FROM {NOTIFICATIONS} "  # noqa: S608 - module constants only
        "WHERE kind IN ('challenge_completed', 'challenge_failed')"
    )
    _replace_check(NOTIFICATIONS, KIND, f"kind IN {OLD_KINDS}")

    op.drop_index(CHALLENGE_RUN_INDEX, VERSIONS)
    op.drop_column(VERSIONS, "idempotency_key")
    op.execute(f"UPDATE {VERSIONS} SET source = 'assessments' WHERE source = 'challenge'")  # noqa: S608
    _replace_check(
        VERSIONS, SOURCE_HAS_RUN, "(source = 'assessments') = (source_run_id IS NOT NULL)"
    )
    _replace_check(VERSIONS, SOURCE, "source IN ('model', 'assessments')")
