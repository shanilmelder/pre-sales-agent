"""Read models of Workflow Runs (Story 5.2; moved from `assessments`, Epic 5 slice 5A), and
the Assessments tab's view composed from them and `assessments`' public API. Class names are
part of the API schema and unchanged."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.assessments.application.public import (
    AgentAssessment,
    RunErrorCode,
)
from app.modules.workflows.domain.runs import (
    AssessmentRunStatus,
    AssessmentTaskStatus,
    DecisionChoice,
    DecisionKind,
    DecisionStatus,
    TaskAgent,
    TaskSkipReason,
)


class AssessmentTask(BaseModel):
    """One agent's task in an assessment run: a specialist's, or (Story 6.4) the Critic's,
    which runs once the specialists' have ended. `error_code` is set only when `failed`;
    `skip_reason` only when `skipped` because a person continued without its disabled Agent
    (`agent_disabled`: the panel says "Agent disabled — assess manually"); a cancel's skipped
    tasks have none.
    `started_at` / `finished_at`: when the task last started and finished (null before
    either); the panel derives elapsed time from them."""

    agent: TaskAgent
    status: AssessmentTaskStatus
    error_code: RunErrorCode | None
    skip_reason: TaskSkipReason | None = None
    started_at: datetime | None
    finished_at: datetime | None


class RunDecision(BaseModel):
    """A decision the run waits on, or waited on (Story 5.5). `plan_escalation`: the task of
    `agent` was not planned because its Agent is disabled; **Continue without** skips it,
    **Re-plan** runs it once the Agent is active again (`agent_active`). `row_version`: for
    `If-Match` on the resolve. `resolved_by`: the resolver's name."""

    id: str
    kind: DecisionKind
    agent: TaskAgent
    agent_name: str
    agent_active: bool
    status: DecisionStatus
    choice: DecisionChoice | None
    row_version: int
    created_at: datetime
    resolved_by: str | None
    resolved_at: datetime | None


class PlanVersionTask(BaseModel):
    """One task of a plan version: its Agent and the config version it was pinned to
    (`config_version`: that version's number for the Agent)."""

    agent: TaskAgent
    config_version_id: str
    config_version: int | None


class PlanVersion(BaseModel):
    """One version of the run's plan (FR-15): v1 when the run was queued, one more per
    Re-plan. `created_by`: who made it (a person's name, or "System" for an automatic run)."""

    version: int
    created_by: str
    created_at: datetime
    tasks: list[PlanVersionTask]


class AssessmentRun(BaseModel):
    """An assessment run: its status and one task per agent, in agent order. `queued_at`:
    when it was last queued (a retry or a resolved decision re-queues it); `finished_at`:
    null while in progress, or for a lost run not yet recorded. `waiting_for_human`: paused
    on an open decision in `decisions` (Story 5.5). `plan_version`: its current plan;
    `plan_versions`: every version, oldest first."""

    id: str
    status: AssessmentRunStatus
    created_at: datetime
    queued_at: datetime
    finished_at: datetime | None
    tasks: list[AssessmentTask]
    plan_version: int = 1
    decisions: list[RunDecision] = []
    plan_versions: list[PlanVersion] = []


class DecisionResolution(BaseModel):
    """How a person resolves a run's decision."""

    model_config = ConfigDict(extra="forbid")

    choice: DecisionChoice


class AssessmentsView(BaseModel):
    """The Opportunity's latest assessment run (null before the first) with its tasks, and
    one entry per agent (Engineering, PM, Security) with its current Assessment or null.
    `can_start`: whether the caller may start a run or retry a task; `can_resolve`: whether
    they may resolve the run's decisions (Story 5.5). The UI only uses them to hide
    controls; the API decides."""

    run: AssessmentRun | None
    assessments: list[AgentAssessment]
    can_start: bool
    can_resolve: bool = False


class ProgressEventData(BaseModel):
    """The `data` of an event-stream frame (AD-30): ids, the event type, when it occurred,
    and a summary of Agent ids and statuses, never customer text."""

    event_type: Literal[
        "workflows.run.queued",
        "workflows.task.started",
        "workflows.task.ended",
        "workflows.run.ended",
        "workflows.run.waiting_for_human",
    ]
    subject_type: str
    subject_id: str
    subject_version: int | None
    occurred_at: datetime
    summary: str


class TraceEventData(BaseModel):
    """The `data` of a trace frame on the event stream (Story 2.3): the trace row's event
    type, subject and time. `summary` is the event type; the trace payload is never sent."""

    event_type: str
    subject_type: str
    subject_id: str
    subject_version: int | None
    occurred_at: datetime
    summary: str
