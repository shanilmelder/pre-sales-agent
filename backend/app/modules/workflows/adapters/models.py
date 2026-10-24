"""The workflows module's tables (Story 5.2): runs, their tasks and the progress rows; and
(Story 5.5, pause and resume) the decisions a run waits on and every version of its plan.

`workflows_runs` and `workflows_tasks` are the former `assessments_runs` and
`assessments_tasks`, renamed in place (ids and history kept). `opportunity_id` holds an id
owned by `opportunities` without a foreign key (AD-2); `config_version_id` references the
Agent Registry, as Story 7.1 specified.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")
_AGENTS = "('engineering_agent', 'pm_agent', 'security_agent', 'critic_agent')"
_ERROR_CODES = "('model_unavailable', 'model_timeout', 'output_invalid')"
PROGRESS_EVENTS = (
    "workflows.run.queued",
    "workflows.task.started",
    "workflows.task.ended",
    "workflows.run.ended",
    "workflows.run.waiting_for_human",
)
RUN_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "partially_failed",
    "failed",
    "cancelled",
    "waiting_for_human",
)


class WorkflowRunRow(Base):
    """One Workflow Run of an Opportunity: one task per planned Agent. Inserted `queued` with
    its job; its status follows its tasks', except `cancelled` (Story 5.5), which a person
    sets, and `waiting_for_human` (Story 5.5), set while a decision is open. `queued_at`:
    when it was last queued (a task retry or a resolved decision queues it again);
    staleness counts from there. `plan_version`: the plan it was built with (1 until plans can be
    edited; a Re-plan bumps it)."""

    __tablename__ = "workflows_runs"
    __table_args__ = (
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in RUN_STATUSES) + ")",
            name="status",
        ),
        CheckConstraint("plan_version >= 1", name="plan_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    plan_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowTaskRow(Base):
    """One Agent's task in a run. `error_code` is set only when `failed`; `skipped` when its
    run was cancelled before it finished (Story 5.5), its Agent was not active in the Agent
    Registry before it started (`skip_reason` `agent_disabled`, Story 7.1), or a task it
    `requires` ended without succeeding (Story 5.2). `requires`: the ids of the run's tasks it
    waits for (empty: it starts at once). `after` (Story 6.4): the ids of the run's tasks it
    starts after, once each has ended whatever the outcome (the Critic's: the specialists').
    `config_version_id`: the registry config version pinned when the run was queued."""

    __tablename__ = "workflows_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "agent"),
        CheckConstraint(f"agent IN {_AGENTS}", name="agent"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')", name="status"
        ),
        CheckConstraint(f"error_code IS NULL OR error_code IN {_ERROR_CODES}", name="error_code"),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
        CheckConstraint(
            "skip_reason IS NULL OR (status = 'skipped' AND skip_reason IN ('agent_disabled'))",
            name="skip_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workflows_runs.id", ondelete="CASCADE", name="fk_workflows_tasks_run_id"),
    )
    agent: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    config_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "registry_agent_config_versions.id", name="fk_workflows_tasks_config_version_id"
        ),
    )
    skip_reason: Mapped[str | None] = mapped_column(Text)
    requires: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
    after: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowProgressRow(Base):
    """A progress row (AD-24, AD-30): a task started or ended, a run was queued or ended.
    Not an audit record: no actor, and pruned after 30 days. `summary` holds Agent ids and
    statuses only, never customer text. Each insert also NOTIFYs `psa_events`."""

    __tablename__ = "workflows_progress"
    __table_args__ = (
        Index(None, "opportunity_id", "id"),
        Index(None, "occurred_at"),
        CheckConstraint(
            "event_type IN (" + ", ".join(f"'{e}'" for e in PROGRESS_EVENTS) + ")",
            name="event_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workflows_runs.id", ondelete="CASCADE", name="fk_workflows_progress_run_id"),
    )
    task_id: Mapped[UUID | None] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(Text)
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    subject_version: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class WorkflowDecisionRow(Base):
    """A decision a run waits on (Story 5.5): a `plan_escalation` for a task whose Agent is
    not active. Recorded `open` once per (run, task, kind) before the node interrupts;
    `resolved` with the person's `choice`, or `cancelled` with its run. `payload` holds ids
    and codes only. `row_version` is the `If-Match` of the resolve command."""

    __tablename__ = "workflows_decisions"
    __table_args__ = (
        UniqueConstraint("run_id", "task_id", "kind"),
        CheckConstraint("kind IN ('plan_escalation')", name="kind"),
        CheckConstraint("status IN ('open', 'resolved', 'cancelled')", name="status"),
        CheckConstraint(
            "choice IS NULL OR choice IN ('continue_without', 'replan')", name="choice"
        ),
        CheckConstraint(
            "(status = 'resolved') = (choice IS NOT NULL AND resolved_at IS NOT NULL)",
            name="resolved_has_choice",
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workflows_runs.id", ondelete="CASCADE", name="fk_workflows_decisions_run_id"),
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workflows_tasks.id", ondelete="CASCADE", name="fk_workflows_decisions_task_id"),
    )
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    choice: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class WorkflowPlanVersionRow(Base):
    """One version of a run's plan (FR-15; Story 5.5): per task its Agent, pinned config
    version and (Story 6.4) the tasks it runs after (`tasks`: `[{task_id, agent,
    config_version_id, after}]`), who made it and when. v1 is
    written when the run is queued, v2+ on each Re-plan. Insert-only."""

    __tablename__ = "workflows_plan_versions"
    __table_args__ = (
        UniqueConstraint("run_id", "version"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "workflows_runs.id", ondelete="CASCADE", name="fk_workflows_plan_versions_run_id"
        ),
    )
    version: Mapped[int] = mapped_column(Integer)
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_by_type: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
