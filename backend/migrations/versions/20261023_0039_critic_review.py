"""Critic Review (Story 6.4).

- `assessments_reviews`: `kind` widened to `('red_team', 'critic')`; nullable `run_id` (the
  assessment run a Critic Review reviewed, a Workflow Run id without a foreign key, AD-2).
- `assessments_findings.category` widened with the Critic's categories (`coverage`,
  `unsupported_claim`, `timeline`, `dependency`, `risk_coverage`).
- `assessments_finding_targets` (`finding_id`, `assessment_finding_id`, `assessment_id`,
  `assessment_version`): the specialist Findings a Critic Finding cites, at their Assessment
  version. `psa_app`: SELECT, INSERT only.
- `workflows_tasks`: `after uuid[] NOT NULL DEFAULT '{}'` (the tasks it starts after, once
  each has ended whatever the outcome); `agent` widened with `critic_agent`.
- Seed: `critic_agent` ("Critic Agent"), `active`, with config version 1 as 0033 seeded the
  Conflict Agent (0.1.0, profile `demo-chat`, prompt 1, schemas 1, contract "1", no budgets,
  digest `unpinned`), granting the read-only tool `assessments.run.read`. Ids are
  deterministic: `uuid5(SEED_NAMESPACE, "critic_agent")` and `uuid5(SEED_NAMESPACE,
  "critic_agent/config/1")`. The seed is a literal: this migration never imports the app.

Downgrade deletes the Critic's tasks (their decisions cascade), Critic Reviews (their
Findings and links cascade), the Agent and its config versions, then drops the table and
columns and restores the checks.

Revision ID: 0039_critic_review
Revises: 0038_tool_gateway
Create Date: 2026-10-23
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_critic_review"
down_revision: str | None = "0038_tool_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
AGENTS = "registry_agents"
VERSIONS = "registry_agent_config_versions"
REVIEWS = "assessments_reviews"
FINDINGS = "assessments_findings"
TARGETS = "assessments_finding_targets"
TASKS = "workflows_tasks"

SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE` (a test checks it)."""
SEED_AGENTS: tuple[tuple[str, str], ...] = (("critic_agent", "Critic Agent"),)
SEED_SEMVER = "0.1.0"
SEED_PROFILE = "demo-chat"
SEED_CONTRACT = "1"
SEED_TOOLS = ("assessments.run.read",)

# The constraint names 0014 created (the naming convention applied to an already full name).
KIND_CHECK = "ck_assessments_reviews_ck_assessments_reviews_kind"
CATEGORY_CHECK = "ck_assessments_findings_ck_assessments_findings_category"
AGENT_CHECK = "ck_workflows_tasks_agent"

RED_TEAM_CATEGORIES = (
    "integration_harder",
    "requirement_incomplete",
    "capability_overstated",
    "hidden_dependency",
)
CRITIC_CATEGORIES = ("coverage", "unsupported_claim", "timeline", "dependency", "risk_coverage")
SPECIALISTS = ("engineering_agent", "pm_agent", "security_agent")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _agent_row_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, agent_id)


def _seed_version_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{agent_id}/config/1")


def _replace_check(table: str, name: str, condition: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition})")


def upgrade() -> None:
    _replace_check(REVIEWS, KIND_CHECK, "kind IN ('red_team', 'critic')")
    op.add_column(REVIEWS, sa.Column("run_id", sa.Uuid(), nullable=True))
    _replace_check(
        FINDINGS, CATEGORY_CHECK, f"category IN {_in(RED_TEAM_CATEGORIES + CRITIC_CATEGORIES)}"
    )

    op.create_table(
        TARGETS,
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_finding_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            [f"{FINDINGS}.id"],
            name="fk_assessments_finding_targets_finding_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "finding_id", "assessment_finding_id", name="pk_assessments_finding_targets"
        ),
    )
    op.execute(f"GRANT SELECT, INSERT ON {TARGETS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {TARGETS} FROM {APP_ROLE}")

    op.add_column(
        TASKS,
        sa.Column(
            "after",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    _replace_check(TASKS, AGENT_CHECK, f"agent IN {_in((*SPECIALISTS, 'critic_agent'))}")

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
                "tool_permissions": json.loads(json.dumps(list(SEED_TOOLS))),
                "budgets": json.loads("{}"),
            }
            for agent_id, _ in SEED_AGENTS
        ],
    )


def downgrade() -> None:
    for agent_id, _ in SEED_AGENTS:
        # The Critic's tasks pin its config versions; their decisions cascade.
        op.execute(sa.text(f"DELETE FROM {TASKS} WHERE agent = :a").bindparams(a=agent_id))  # noqa: S608 - constants only
        op.execute(
            sa.text(f"DELETE FROM {VERSIONS} WHERE agent_id = :a").bindparams(a=agent_id)  # noqa: S608
        )
        op.execute(
            sa.text(f"DELETE FROM {AGENTS} WHERE agent_id = :a").bindparams(a=agent_id)  # noqa: S608
        )
    _replace_check(TASKS, AGENT_CHECK, f"agent IN {_in(SPECIALISTS)}")
    op.drop_column(TASKS, "after")
    op.drop_table(TARGETS)
    op.execute(f"DELETE FROM {REVIEWS} WHERE kind = 'critic'")  # noqa: S608 - its Findings cascade
    _replace_check(FINDINGS, CATEGORY_CHECK, f"category IN {_in(RED_TEAM_CATEGORIES)}")
    op.drop_column(REVIEWS, "run_id")
    _replace_check(REVIEWS, KIND_CHECK, "kind = 'red_team'")
