"""Workflow Run rules (Story 5.2): run and task states, the run's status from its tasks', the
plan's dependency checks and the progress vocabulary. Pure.

A run has one task per planned Agent: one per specialist, and (Story 6.4) one
`critic_agent` task. Tasks run concurrently unless a task `requires` others (it starts only
once all of them succeeded, and is skipped once one of them ended any other way) or runs
`after` others (it starts once all of them ended, whatever the outcome). The statuses keep
the vocabulary of the assessment runs they were moved from (Epic 5 slice 5A, Story 5.5):
enum names are part of the API schema.
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


class TaskAgent(StrEnum):
    """The Agents a run plans a task for, in the order they are listed: the specialists, then
    the Critic (Story 6.4)."""

    ENGINEERING = "engineering_agent"
    PM = "pm_agent"
    SECURITY = "security_agent"
    CRITIC = "critic_agent"


TASK_AGENTS: tuple[TaskAgent, ...] = tuple(TaskAgent)


def task_agent_rank(agent: str) -> int:
    """An Agent's place in `TASK_AGENTS`; unknown ones last."""
    try:
        return TASK_AGENTS.index(TaskAgent(agent))
    except ValueError:
        return len(TASK_AGENTS)


class AssessmentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    """Stopped by a person (Story 5.5): set directly by the cancel command, never derived from
    the tasks', and final (nothing moves a cancelled run again)."""
    WAITING_FOR_HUMAN = "waiting_for_human"
    """Paused on an open decision (Story 5.5, pause and resume): set when the graph returns
    with a task waiting for a person and none running; resolving the decision queues the
    run again. Never derived from the tasks'."""


RUN_IN_PROGRESS = frozenset({AssessmentRunStatus.QUEUED, AssessmentRunStatus.RUNNING})
"""A run a job is working on (or about to): queued or running. The Estimate tab's "run in
progress" and stale-run handling use this."""
RUN_ACTIVE = RUN_IN_PROGRESS | {AssessmentRunStatus.WAITING_FOR_HUMAN}
"""A run that is not finished: in progress, or waiting for a person. A new start is 409
while one is active, an automatic run coalesces with it, and it can be cancelled."""


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


def readiness(
    requires: Sequence[UUID],
    statuses: Mapping[UUID, AssessmentTaskStatus],
    after: Sequence[UUID] = (),
) -> Readiness:
    """Whether a task may start: `ready` when every task it requires succeeded and every task
    it runs `after` has ended, whatever the outcome (Story 6.4); `blocked` when a required
    task ended without succeeding; else `waiting`. A task that is not in the run is
    ignored."""
    known = [statuses[r] for r in requires if r in statuses]
    if any(s not in TASK_IN_PROGRESS and s != AssessmentTaskStatus.SUCCEEDED for s in known):
        return "blocked"
    if not all(s == AssessmentTaskStatus.SUCCEEDED for s in known):
        return "waiting"
    if any(statuses[a] in TASK_IN_PROGRESS for a in after if a in statuses):
        return "waiting"
    return "ready"


class ProgressEvent(StrEnum):
    """`workflows_progress.event_type`: what a progress row reports (Story 5.2)."""

    RUN_QUEUED = "workflows.run.queued"
    TASK_STARTED = "workflows.task.started"
    TASK_ENDED = "workflows.task.ended"
    RUN_ENDED = "workflows.run.ended"
    RUN_WAITING = "workflows.run.waiting_for_human"


class DecisionKind(StrEnum):
    """`workflows_decisions.kind`: what a person is asked to decide (Story 5.5)."""

    PLAN_ESCALATION = "plan_escalation"
    """A task's Agent is `disabled` or `eval_only`: go on without it, or re-plan once it is
    active again."""


class DecisionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    """Its run was cancelled while it was open: it can no longer be resolved."""


class DecisionChoice(StrEnum):
    """What a person chose for a `plan_escalation`."""

    CONTINUE_WITHOUT = "continue_without"
    """The task is skipped (`agent_disabled`) and the run goes on without it."""
    REPLAN = "replan"
    """The task is re-pinned to its Agent's current config version (a new plan version) and
    runs. Allowed only once the Agent is active again."""


PROGRESS_RETENTION_DAYS = 30
"""Progress rows older than this are pruned (they are not audit records)."""


def task_summary(agent: str, status: AssessmentTaskStatus) -> str:
    """A progress row's summary for a task: its Agent id and status, never customer text."""
    return f"{agent} {status.value}"


def waiting_summary(agent: str) -> str:
    """A waiting run's progress summary: the Agent id it waits on, never customer text."""
    return f"{agent} waiting_for_human"


def run_summary(status: AssessmentRunStatus) -> str:
    return f"run {status.value}"
