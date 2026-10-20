"""Read models of Workflow Runs (Story 5.2; moved from `assessments`, Epic 5 slice 5A), and
the Assessments tab's view composed from them and `assessments`' public API. Class names are
part of the API schema and unchanged."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.assessments.application.public import (
    AgentAssessment,
    AssessmentAgent,
    RunErrorCode,
)
from app.modules.workflows.domain.runs import (
    AssessmentRunStatus,
    AssessmentTaskStatus,
    TaskSkipReason,
)


class AssessmentTask(BaseModel):
    """One agent's task in an assessment run. `error_code` is set only when `failed`;
    `skip_reason` only when `skipped` because its Agent is disabled (`agent_disabled`: the
    panel says "Agent disabled — assess manually"); a cancel's skipped tasks have none.
    `started_at` / `finished_at`: when the task last started and finished (null before
    either); the panel derives elapsed time from them."""

    agent: AssessmentAgent
    status: AssessmentTaskStatus
    error_code: RunErrorCode | None
    skip_reason: TaskSkipReason | None = None
    started_at: datetime | None
    finished_at: datetime | None


class AssessmentRun(BaseModel):
    """An assessment run: its status and one task per agent, in agent order. `queued_at`:
    when it was last queued (a retry re-queues it); `finished_at`: null while in progress,
    or for a lost run not yet recorded."""

    id: str
    status: AssessmentRunStatus
    created_at: datetime
    queued_at: datetime
    finished_at: datetime | None
    tasks: list[AssessmentTask]


class AssessmentsView(BaseModel):
    """The Opportunity's latest assessment run (null before the first) with its tasks, and
    one entry per agent (Engineering, PM, Security) with its current Assessment or null.
    `can_start`: whether the caller may start a run or retry a task. The UI only uses it to
    hide controls; the API decides."""

    run: AssessmentRun | None
    assessments: list[AgentAssessment]
    can_start: bool


class ProgressEventData(BaseModel):
    """The `data` of an event-stream frame (AD-30): ids, the event type, when it occurred,
    and a summary of Agent ids and statuses, never customer text."""

    event_type: Literal[
        "workflows.run.queued",
        "workflows.task.started",
        "workflows.task.ended",
        "workflows.run.ended",
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
