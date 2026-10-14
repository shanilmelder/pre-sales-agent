"""The workflows module's tables (Story 5.2): runs, their tasks and the progress rows.

`workflows_runs` and `workflows_tasks` are the former `assessments_runs` and
`assessments_tasks`, renamed in place (ids and history kept). `opportunity_id` holds an id
owned by `opportunities` without a foreign key (AD-2); `config_version_id` references the
Agent Registry, as Story 7.1 specified.
"""

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")
_AGENTS = "('engineering_agent', 'pm_agent', 'security_agent')"
_ERROR_CODES = "('model_unavailable', 'model_timeout', 'output_invalid')"
PROGRESS_EVENTS = (
    "workflows.run.queued",
    "workflows.task.started",
    "workflows.task.ended",
    "workflows.run.ended",
)


class WorkflowRunRow(Base):
    """One Workflow Run of an Opportunity: one task per planned Agent. Inserted `queued` with
    its job; its status follows its tasks', except `cancelled` (Story 5.5), which a person
    sets. `queued_at`: when it was last queued (a task retry queues it again); staleness
    counts from there. `plan_version`: the plan it was built with (1 until plans can be
    edited)."""

    __tablename__ = "workflows_runs"
    __table_args__ = (
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partially_failed', 'failed', "
            "'cancelled')",
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
    waits for (empty: it starts at once). `config_version_id`: the registry config version
    pinned when the run was queued."""

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
