"""The DB-owned Agent Registry with immutable config versions (Story 7.1).

- `registry_agents`: one row per Agent (`agent_id` unique, `^[a-z][a-z0-9_]*_agent$`; `name`;
  `status` `active | disabled | eval_only`; `row_version`). `psa_app`: SELECT, INSERT,
  UPDATE (no DELETE).
- `registry_agent_config_versions`: immutable config versions, numbered 1, 2, … per Agent
  (semver, model profile, model digest `unpinned` until Story 7.2, prompt version, input and
  output schema versions, contract version, tool permissions, budgets, created by and at).
  `psa_app`: SELECT, INSERT only.
- Seed: the 8 Agents the code defined until now, each `active` with config version 1
  (0.1.0, profile `demo-chat`, prompt 1, schemas 1, contract "1", no tool permissions, no
  budgets). Ids are deterministic: `uuid5(SEED_NAMESPACE, agent_id)` for the Agent and
  `uuid5(SEED_NAMESPACE, "<agent_id>/config/1")` for its version 1. The seed is a literal:
  this migration never imports the app.
- `assessments_assessments.config_version_id` (FK, NOT NULL): the config version that
  produced each Assessment. Existing ones are backfilled to their agent's version 1 (every
  existing Assessment was produced by 0.1.0 with prompt 1).
- `assessments_tasks.config_version_id` (FK, NOT NULL): the version the task pinned when its
  run was queued (backfilled the same way), and `skip_reason` (`agent_disabled`, set only on a
  `skipped` task whose Agent was not active). `psa_app` may UPDATE `skip_reason`, never the
  pinned version.
- The single-agent runs' `error_code` gains `registry_agent_disabled`
  (`assessments_red_team_runs`, `gaps_detections`, `estimates_drafts`, `intake_extractions`,
  `opportunities_imports`).

Revision ID: 0026_registry
Revises: 0025_knowledge_sources
Create Date: 2026-10-13
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_registry"
down_revision: str | None = "0025_knowledge_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
AGENTS = "registry_agents"
VERSIONS = "registry_agent_config_versions"
ASSESSMENTS = "assessments_assessments"
TASKS = "assessments_tasks"
ASSESSMENT_FK = "fk_assessments_assessments_config_version_id"
TASK_FK = "fk_assessments_tasks_config_version_id"

SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE` (a test checks it)."""
SEED_AGENTS: tuple[tuple[str, str], ...] = (
    ("clarification_agent", "Clarification Agent"),
    ("engineering_agent", "Engineering Agent"),
    ("estimating_agent", "Estimating Agent"),
    ("intake_agent", "Intake Agent"),
    ("opportunity_intake_agent", "Opportunity Intake Agent"),
    ("pm_agent", "PM Agent"),
    ("red_team_agent", "Red Team Agent"),
    ("security_agent", "Security Agent"),
)
SEED_SEMVER = "0.1.0"
SEED_PROFILE = "demo-chat"
SEED_CONTRACT = "1"
SPECIALISTS = ("engineering_agent", "pm_agent", "security_agent")

ERROR_CODES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "assessments_red_team_runs",
        "ck_assessments_red_team_runs_error_code",
        ("model_unavailable", "model_timeout", "output_invalid"),
    ),
    (
        "gaps_detections",
        "ck_gaps_detections_error_code",
        ("model_unavailable", "model_timeout", "output_invalid"),
    ),
    (
        "estimates_drafts",
        "ck_estimates_drafts_error_code",
        ("model_unavailable", "model_timeout", "output_invalid"),
    ),
    (
        "intake_extractions",
        "ck_intake_extractions_error_code",
        ("model_unavailable", "model_timeout", "output_invalid", "input_too_large"),
    ),
    (
        "opportunities_imports",
        "ck_opportunities_imports_error_code",
        ("unreadable", "model_unavailable", "model_timeout", "output_invalid"),
    ),
)
DISABLED_CODE = "registry_agent_disabled"


def _now() -> sa.TextClause:
    return sa.text("now()")


def _agent_row_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, agent_id)


def _seed_version_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{agent_id}/config/1")


def _codes(codes: Sequence[str]) -> str:
    return "error_code IS NULL OR error_code IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    op.create_table(
        AGENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "agent_id ~ '^[a-z][a-z0-9_]*_agent$'", name="ck_registry_agents_agent_id"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'eval_only')", name="ck_registry_agents_status"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_registry_agents"),
        sa.UniqueConstraint("agent_id", name="uq_registry_agents_agent_id"),
    )
    op.create_table(
        VERSIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("semver", sa.Text(), nullable=False),
        sa.Column("model_profile", sa.Text(), nullable=False),
        sa.Column("model_digest", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("input_schema_version", sa.Integer(), nullable=False),
        sa.Column("output_schema_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("tool_permissions", postgresql.JSONB(), nullable=False),
        sa.Column("budgets", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_registry_agent_config_versions_version"),
        sa.CheckConstraint(
            "prompt_version >= 1 AND input_schema_version >= 1 AND output_schema_version >= 1",
            name="ck_registry_agent_config_versions_versions",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            [f"{AGENTS}.agent_id"],
            name="fk_registry_agent_config_versions_agent_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_registry_agent_config_versions"),
        sa.UniqueConstraint(
            "agent_id", "version", name="uq_registry_agent_config_versions_agent_id_version"
        ),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {AGENTS} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE, TRUNCATE ON {AGENTS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {VERSIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {VERSIONS} FROM {APP_ROLE}")

    # --- the seed ---------------------------------------------------------------------------
    agents = sa.table(
        AGENTS,
        sa.column("id", sa.Uuid()),
        sa.column("agent_id", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("status", sa.Text()),
        sa.column("row_version", sa.Integer()),
    )
    versions = sa.table(
        VERSIONS,
        sa.column("id", sa.Uuid()),
        sa.column("agent_id", sa.Text()),
        sa.column("version", sa.Integer()),
        sa.column("semver", sa.Text()),
        sa.column("model_profile", sa.Text()),
        sa.column("model_digest", sa.Text()),
        sa.column("prompt_version", sa.Integer()),
        sa.column("input_schema_version", sa.Integer()),
        sa.column("output_schema_version", sa.Integer()),
        sa.column("contract_version", sa.Text()),
        sa.column("tool_permissions", postgresql.JSONB()),
        sa.column("budgets", postgresql.JSONB()),
    )
    op.bulk_insert(
        agents,
        [
            {
                "id": _agent_row_id(agent_id),
                "agent_id": agent_id,
                "name": name,
                "status": "active",
                "row_version": 1,
            }
            for agent_id, name in SEED_AGENTS
        ],
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": _seed_version_id(agent_id),
                "agent_id": agent_id,
                "version": 1,
                "semver": SEED_SEMVER,
                "model_profile": SEED_PROFILE,
                "model_digest": "unpinned",
                "prompt_version": 1,
                "input_schema_version": 1,
                "output_schema_version": 1,
                "contract_version": SEED_CONTRACT,
                "tool_permissions": json.loads("[]"),
                "budgets": json.loads("{}"),
            }
            for agent_id, _ in SEED_AGENTS
        ],
    )

    # --- Assessments and tasks pin their config version ------------------------------------
    for table, fk in ((ASSESSMENTS, ASSESSMENT_FK), (TASKS, TASK_FK)):
        op.add_column(table, sa.Column("config_version_id", sa.Uuid(), nullable=True))
        for agent_id in SPECIALISTS:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET config_version_id = :v "  # noqa: S608 - constants only
                    "WHERE agent = :a AND config_version_id IS NULL"
                ).bindparams(v=_seed_version_id(agent_id), a=agent_id)
            )
        op.alter_column(table, "config_version_id", nullable=False)
        op.create_foreign_key(fk, table, VERSIONS, ["config_version_id"], ["id"])
    op.add_column(TASKS, sa.Column("skip_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_assessments_tasks_skip_reason",
        TASKS,
        "skip_reason IS NULL OR (status = 'skipped' AND skip_reason IN ('agent_disabled'))",
    )
    # The pinned version never changes; the skip reason moves with the status.
    op.execute(f"GRANT UPDATE (skip_reason) ON {TASKS} TO {APP_ROLE}")

    # --- single-agent runs can fail because their Agent is disabled ---------------------------
    for table, name, codes in ERROR_CODES:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _codes((*codes, DISABLED_CODE)))


def downgrade() -> None:
    for table, name, codes in ERROR_CODES:
        # The older code has no such code: a run its Agent's status failed reads as the
        # model being unavailable.
        op.execute(
            f"UPDATE {table} SET error_code = 'model_unavailable' "  # noqa: S608 - constants only
            f"WHERE error_code = '{DISABLED_CODE}'"
        )
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _codes(codes))
    op.drop_constraint("ck_assessments_tasks_skip_reason", TASKS, type_="check")
    op.drop_column(TASKS, "skip_reason")
    for table, fk in ((TASKS, TASK_FK), (ASSESSMENTS, ASSESSMENT_FK)):
        op.drop_constraint(fk, table, type_="foreignkey")
        op.drop_column(table, "config_version_id")
    op.drop_table(VERSIONS)
    op.drop_table(AGENTS)
