"""Workflow Run rules (Story 5.2): run and task states, the run's status from its tasks', the
plan's dependency checks and the progress vocabulary. Pure.

A run has one task per planned Agent. Tasks run concurrently unless a task `requires`
others: it starts only once all of them succeeded, and is skipped once one of them ended any
other way. The statuses keep the vocabulary of the assessment runs they were moved from
(Epic 5 slice 5A, Story 5.5): enum names are part of the API schema.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Literal
from uuid import UUID

RUN_SUBJECT_TYPE = "assessments.assessment_run"
"""The trace subject of a run (unchanged from when `assessments` owned runs)."""
TASK_PROGRESS_SUBJECT = "workflows.task"
RUN_PROGRESS_SUBJECT = "workflows.run"
PLAN_VERSION = 1
"""The plan version every run is planned with until plans can be edited."""


class AssessmentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    """Stopped by a person (Story 5.5): set directly by the cancel command, never derived from
    the tasks', and final (nothing moves a cancelled run again)."""


RUN_IN_PROGRESS = frozenset({AssessmentRunStatus.QUEUED, AssessmentRunStatus.RUNNING})


class AssessmentTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    """Unfinished when its run was cancelled (Story 5.5), its Agent was not active in the
    Agent Registry before it started (Story 7.1, with a `skip_reason`), or a task it requires
    ended without succeeding (Story 5.2)."""


TASK_IN_PROGRESS = frozenset({AssessmentTaskStatus.QUEUED, AssessmentTaskStatus.RUNNING})


class TaskSkipReason(StrEnum):
    """Why a task was skipped other than by a cancel (Story 7.1)."""

    AGENT_DISABLED = "agent_disabled"
    """Its Agent was `disabled` or `eval_only`: assess that part manually."""


def run_status(tasks: Iterable[AssessmentTaskStatus]) -> AssessmentRunStatus:
    """A run's status from its tasks': `queued` while every task is queued, `running` while
    any is still queued or running, then `succeeded` when all succeeded, `failed` when none
    did, otherwise `partially_failed`. A `cancelled` run is never derived: the cancel sets it."""
    statuses = list(tasks)
    if statuses and all(s == AssessmentTaskStatus.QUEUED for s in statuses):
        return AssessmentRunStatus.QUEUED
    if any(s in TASK_IN_PROGRESS for s in statuses):
        return AssessmentRunStatus.RUNNING
    succeeded = sum(1 for s in statuses if s == AssessmentTaskStatus.SUCCEEDED)
    if succeeded == len(statuses):
        return AssessmentRunStatus.SUCCEEDED
    if succeeded == 0:
        return AssessmentRunStatus.FAILED
    return AssessmentRunStatus.PARTIALLY_FAILED


Readiness = Literal["ready", "waiting", "blocked"]


def readiness(requires: Sequence[UUID], statuses: Mapping[UUID, AssessmentTaskStatus]) -> Readiness:
    """Whether a task may start: `ready` when every task it requires succeeded (or it
    requires none), `blocked` when one of them ended any other way, else `waiting`. A
    required task that is not in the run is ignored."""
    known = [statuses[r] for r in requires if r in statuses]
    if any(s not in TASK_IN_PROGRESS and s != AssessmentTaskStatus.SUCCEEDED for s in known):
        return "blocked"
    if all(s == AssessmentTaskStatus.SUCCEEDED for s in known):
        return "ready"
    return "waiting"


class ProgressEvent(StrEnum):
    """`workflows_progress.event_type`: what a progress row reports (Story 5.2)."""

    RUN_QUEUED = "workflows.run.queued"
    TASK_STARTED = "workflows.task.started"
    TASK_ENDED = "workflows.task.ended"
    RUN_ENDED = "workflows.run.ended"


PROGRESS_RETENTION_DAYS = 30
"""Progress rows older than this are pruned (they are not audit records)."""


def task_summary(agent: str, status: AssessmentTaskStatus) -> str:
    """A progress row's summary for a task: its Agent id and status, never customer text."""
    return f"{agent} {status.value}"


def run_summary(status: AssessmentRunStatus) -> str:
    return f"run {status.value}"
