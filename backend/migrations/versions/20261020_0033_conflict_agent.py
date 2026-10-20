"""LLM-assisted Conflict detection (Story 6.2).

- Seed: `conflict_agent` ("Conflict Agent"), `active`, with config version 1 as 0026 seeded
  the others (0.1.0, profile `demo-chat`, prompt 1, schemas 1, contract "1", no tool
  permissions, no budgets, digest `unpinned`). Ids are deterministic:
  `uuid5(SEED_NAMESPACE, "conflict_agent")` and `uuid5(SEED_NAMESPACE,
  "conflict_agent/config/1")`. The seed is a literal: this migration never imports the app.
- `conflicts_positions.finding_id` (nullable, a plain Uuid like `assessment_id`: an
  `assessments_assessment_findings` id, no foreign key, AD-2): the Finding a semantic
  Conflict's position cites.
- `conflicts_detections`: one row per detection pass of a run (run id, pass, Opportunity,
  when), so a pass is numbered one past the run's latest even when it raised nothing, and the
  semantic job can tell that a newer pass or run has happened. `psa_app`: SELECT, INSERT.
  Existing passes are backfilled from the stored Conflicts.

Downgrade drops the table and the column, and deletes the Agent and its config versions
(nothing pins them: Assessments and tasks only pin the specialists' versions).

Revision ID: 0033_conflict_agent
Revises: 0032_gaps_answers
Create Date: 2026-10-20
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_conflict_agent"
down_revision: str | None = "0032_gaps_answers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
AGENTS = "registry_agents"
VERSIONS = "registry_agent_config_versions"
POSITIONS = "conflicts_positions"
DETECTIONS = "conflicts_detections"

SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE` (a test checks it)."""
SEED_AGENTS: tuple[tuple[str, str], ...] = (("conflict_agent", "Conflict Agent"),)
SEED_SEMVER = "0.1.0"
SEED_PROFILE = "demo-chat"
SEED_CONTRACT = "1"


def _agent_row_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, agent_id)


def _seed_version_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{agent_id}/config/1")


def upgrade() -> None:
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

    op.add_column(POSITIONS, sa.Column("finding_id", sa.Uuid(), nullable=True))

    op.create_table(
        DETECTIONS,
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("detection_pass", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("detection_pass >= 1", name="ck_conflicts_detections_detection_pass"),
        sa.PrimaryKeyConstraint("run_id", "detection_pass", name="pk_conflicts_detections"),
    )
    op.create_index(
        "ix_conflicts_detections_opportunity_id_created_at",
        DETECTIONS,
        ["opportunity_id", "created_at"],
    )
    op.execute(
        f"INSERT INTO {DETECTIONS} (run_id, detection_pass, opportunity_id, created_at) "  # noqa: S608 - constants only
        "SELECT run_id, detection_pass, min(opportunity_id::text)::uuid, min(created_at) "
        "FROM conflicts_conflicts GROUP BY run_id, detection_pass"
    )
    op.execute(f"GRANT SELECT, INSERT ON {DETECTIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {DETECTIONS} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_conflicts_detections_opportunity_id_created_at", table_name=DETECTIONS)
    op.drop_table(DETECTIONS)
    op.drop_column(POSITIONS, "finding_id")
    for agent_id, _ in SEED_AGENTS:
        # Assessments and tasks never pin this Agent's versions, so they can go with it.
        op.execute(
            sa.text(f"DELETE FROM {VERSIONS} WHERE agent_id = :a").bindparams(a=agent_id)  # noqa: S608
        )
        op.execute(
            sa.text(f"DELETE FROM {AGENTS} WHERE agent_id = :a").bindparams(a=agent_id)  # noqa: S608
        )
