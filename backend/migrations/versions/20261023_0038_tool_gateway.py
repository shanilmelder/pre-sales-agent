"""The ToolGateway and Research Snapshots (Story 5.4).

- `platform_tool_calls`: one row per ToolGateway call (run, task, Opportunity, agent, config
  version, tool, outcome `ok | denied | failed`, reason code, result count, duration, HTTP
  status). Never content. `psa_app`: SELECT, INSERT only.
- `knowledge_research_snapshots`: an immutable Research Snapshot of one fetched page (id,
  Opportunity, run, task, url, final url, fetched at, HTTP status, content type
  `text/html | text/plain`, the SHA-256 of the raw body and of the extracted text, both
  stored as blobs, and the parser). `psa_app`: SELECT, INSERT only.
- `assessments_assessment_findings.injection_suspected` (boolean, default false): a cited
  Requirement's text read like an injected instruction.
- The specialists (`engineering_agent`, `pm_agent`, `security_agent`) get config version N+1,
  a copy of their current version that grants `intake.requirement.list` and `gaps.gap.list`;
  it becomes current (the newest version) and the Agent's `row_version` is bumped. Ids are
  deterministic: `uuid5(SEED_NAMESPACE, "<agent_id>/config/tool-gateway")`. No trace event
  (this migration never imports the app).

Downgrade: Assessments and tasks pinned to those versions are re-pinned to the version before,
the versions are deleted, and the column and tables are dropped.

Revision ID: 0038_tool_gateway
Revises: 0038_workflows_decisions
Create Date: 2026-10-23
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_tool_gateway"
# Chained after Story 5.5's migration, written alongside in the same tree; on a branch
# without it this revises "0037_requirement_tags".
down_revision: str | None = "0038_workflows_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
CALLS = "platform_tool_calls"
SNAPSHOTS = "knowledge_research_snapshots"
FINDINGS = "assessments_assessment_findings"
AGENTS = "registry_agents"
VERSIONS = "registry_agent_config_versions"
PINNING = ("assessments_assessments", "workflows_tasks")

SEED_NAMESPACE = uuid.UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""Equal to `app.modules.registry.domain.registry.SEED_NAMESPACE`."""
SPECIALISTS = ("engineering_agent", "pm_agent", "security_agent")
GRANTS = ("intake.requirement.list", "gaps.gap.list")


def _version_id(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{agent_id}/config/tool-gateway")


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        CALLS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("config_version_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('ok', 'denied', 'failed')", name="ck_platform_tool_calls_outcome"
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('tool_not_permitted', 'out_of_scope', 'unknown_tool', "
            "'not_allowlisted', 'timeout', 'http_error', 'too_large', 'unsupported_content', "
            "'too_many_redirects', 'parse_failed')",
            name="ck_platform_tool_calls_reason",
        ),
        sa.CheckConstraint(
            "(outcome = 'ok') = (reason IS NULL)", name="ck_platform_tool_calls_reason_set"
        ),
        sa.CheckConstraint(
            "result_count >= 0 AND duration_ms >= 0", name="ck_platform_tool_calls_counts"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_tool_calls"),
    )
    op.create_index("ix_platform_tool_calls_run_id", CALLS, ["run_id"])
    op.create_index(
        "ix_platform_tool_calls_opportunity_id_created_at", CALLS, ["opportunity_id", "created_at"]
    )
    op.execute(f"GRANT SELECT, INSERT ON {CALLS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {CALLS} FROM {APP_ROLE}")

    op.create_table(
        SNAPSHOTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("parser", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "content_type IN ('text/html', 'text/plain')",
            name="ck_knowledge_research_snapshots_content_type",
        ),
        sa.CheckConstraint(
            "http_status BETWEEN 200 AND 299", name="ck_knowledge_research_snapshots_http_status"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_research_snapshots"),
    )
    op.create_index(
        "ix_knowledge_research_snapshots_opportunity_id_fetched_at",
        SNAPSHOTS,
        ["opportunity_id", "fetched_at"],
    )
    op.execute(f"GRANT SELECT, INSERT ON {SNAPSHOTS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {SNAPSHOTS} FROM {APP_ROLE}")

    op.add_column(
        FINDINGS,
        sa.Column(
            "injection_suspected", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )

    grants = json.dumps(list(GRANTS))
    for agent_id in SPECIALISTS:
        op.execute(
            sa.text(
                f"INSERT INTO {VERSIONS} (id, agent_id, version, semver, model_profile, "  # noqa: S608 - constants only
                "model_digest, prompt_version, input_schema_version, output_schema_version, "
                "contract_version, tool_permissions, budgets, created_by) "
                "SELECT :id, v.agent_id, v.version + 1, v.semver, v.model_profile, "
                "v.model_digest, v.prompt_version, v.input_schema_version, "
                "v.output_schema_version, v.contract_version, CAST(:grants AS jsonb), v.budgets, "
                f"NULL FROM {VERSIONS} v WHERE v.agent_id = :a AND v.version = "
                f"(SELECT max(version) FROM {VERSIONS} WHERE agent_id = :a)"
            ).bindparams(id=_version_id(agent_id), a=agent_id, grants=grants)
        )
        op.execute(
            sa.text(
                f"UPDATE {AGENTS} SET row_version = row_version + 1 WHERE agent_id = :a"  # noqa: S608
            ).bindparams(a=agent_id)
        )


def downgrade() -> None:
    for agent_id in SPECIALISTS:
        new = _version_id(agent_id)
        previous = (
            f"(SELECT p.id FROM {VERSIONS} p JOIN {VERSIONS} n ON n.agent_id = p.agent_id "  # noqa: S608
            "AND p.version = n.version - 1 WHERE n.id = :v)"
        )
        for table in PINNING:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET config_version_id = {previous} "  # noqa: S608
                    "WHERE config_version_id = :v"
                ).bindparams(v=new)
            )
        op.execute(sa.text(f"DELETE FROM {VERSIONS} WHERE id = :v").bindparams(v=new))  # noqa: S608
        op.execute(
            sa.text(
                f"UPDATE {AGENTS} SET row_version = row_version + 1 WHERE agent_id = :a"  # noqa: S608
            ).bindparams(a=agent_id)
        )
    op.drop_column(FINDINGS, "injection_suspected")
    op.drop_index("ix_knowledge_research_snapshots_opportunity_id_fetched_at", table_name=SNAPSHOTS)
    op.drop_table(SNAPSHOTS)
    op.drop_index("ix_platform_tool_calls_opportunity_id_created_at", table_name=CALLS)
    op.drop_index("ix_platform_tool_calls_run_id", table_name=CALLS)
    op.drop_table(CALLS)
