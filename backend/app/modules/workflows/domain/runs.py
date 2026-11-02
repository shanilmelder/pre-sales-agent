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
"""The plan version every run starts with; a Re-plan (Story 5.5) adds the next one."""


class TaskAgent(StrEnum):
    """What a run plans a task for, in the order they are listed: the specialists, then (Story
    9.6, a challenge run) Conflict detection, then the Critic (Story 6.4), then (Story 9.6)
    the new Estimate Version. `conflict_detection` and `new_version` are non-agent nodes: no
    config version, no model call."""

    ENGINEERING = "engineering_agent"
    PM = "pm_agent"
    SECURITY = "security_agent"
    CONFLICT_DETECTION = "conflict_detection"
    CRITIC = "critic_agent"
    NEW_VERSION = "new_version"


TASK_AGENTS: tuple[TaskAgent, ...] = tuple(TaskAgent)
NON_AGENT_NODES: frozenset[str] = frozenset(
    {TaskAgent.CONFLICT_DETECTION.value, TaskAgent.NEW_VERSION.value}
)
"""Story 9.6: the plan's tasks that run platform code, not an Agent: never escalated, no
config version."""
AGENT_LABELS: dict[str, str] = {
    TaskAgent.ENGINEERING.value: "Engineering Agent",
    TaskAgent.PM.value: "PM Agent",
    TaskAgent.SECURITY.value: "Security Agent",
    TaskAgent.CONFLICT_DETECTION.value: "Conflict detection",
    TaskAgent.CRITIC.value: "Critic",
    TaskAgent.NEW_VERSION.value: "New version",
}
DECISION_SUBJECT_TYPE = "workflows.decision"
"""An Inbox item's subject when a run waits on a decision (Story 9.2)."""


def decision_summary(agent: str, title: str | None) -> str:
    """The Inbox summary of a run waiting on a decision (Story 9.2): the Agent and the
    Opportunity's title only."""
    head = f"Decision needed: {AGENT_LABELS.get(agent, agent)} is not active"
    return f"{head} — {title}" if title else head


def task_agent_rank(agent: str) -> int:
    """An Agent's place in `TASK_AGENTS`; unknown ones last."""
    try:
        return TASK_AGENTS.index(TaskAgent(agent))
    except ValueError:
        return len(TASK_AGENTS)


class RunType(StrEnum):
    """What started a run (Story 9.5): an assessment of every agent, or a Challenge's
    reassessment of the Assessments its owner confirmed (Story 9.6: then Conflict detection,
    the Critic and the new Estimate Version)."""

    ASSESSMENT = "assessment"
    CHALLENGE = "challenge"


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
    """Paused on an open decision (Story 5.5, pause and resume): its graph interrupted and no
    task is running. Set by the job, never derived from the tasks'; resolving the decision
    queues it again. Never lost however long it waits."""


RUN_IN_PROGRESS = frozenset({AssessmentRunStatus.QUEUED, AssessmentRunStatus.RUNNING})
"""A run a job is working on (or will): the Estimate tab's "run in progress", and what a lost
run can be."""
RUN_ACTIVE = RUN_IN_PROGRESS | {AssessmentRunStatus.WAITING_FOR_HUMAN}
"""A run that is not over: a new start gets 409, `enqueue_run` coalesces with it, a retry
gets 409, and it can be cancelled."""


class AssessmentTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    """Unfinished when its run was cancelled (Story 5.5), a person chose to continue without
    its disabled Agent (Story 5.5, with the `skip_reason` `agent_disabled`), or a task it
    requires ended without succeeding (Story 5.2)."""


TASK_IN_PROGRESS = frozenset({AssessmentTaskStatus.QUEUED, AssessmentTaskStatus.RUNNING})


class TaskSkipReason(StrEnum):
    """Why a task was skipped other than by a cancel (Story 7.1)."""

    AGENT_DISABLED = "agent_disabled"
    """Its Agent was `disabled` or `eval_only` and a person chose **Continue without** (Story
    5.5): assess that part manually."""


# --- decisions (Story 5.5, pause and resume) --------------------------------------------------


class DecisionKind(StrEnum):
    """What a run waits on a person for."""

    PLAN_ESCALATION = "plan_escalation"
    """A queued task's Agent is `disabled` or `eval_only`: continue without it, or re-plan
    once it is active again."""


class DecisionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    """Its run was cancelled, or ended, before anyone resolved it."""


class DecisionChoice(StrEnum):
    CONTINUE_WITHOUT = "continue_without"
    """The task is skipped (`agent_disabled`) and the run goes on."""
    REPLAN = "replan"
    """The task is re-pinned to its Agent's current config version (a new plan version)
    and runs. Only once the Agent is active again."""


PLAN_ESCALATION_CHOICES = (DecisionChoice.CONTINUE_WITHOUT, DecisionChoice.REPLAN)


def run_status(
    tasks: Iterable[AssessmentTaskStatus], *, chosen_skips: int = 0
) -> AssessmentRunStatus:
    """A run's status from its tasks': `queued` while every task is queued, `running` while
    any is still queued or running, then `failed` when none succeeded, `succeeded` when every
    task succeeded or was skipped by choice, otherwise `partially_failed`. `chosen_skips`:
    how many of the `skipped` tasks a person chose to continue without (`agent_disabled`,
    Story 5.5); they don't count against the run (user decision, 2026-10-24). Tasks skipped
    by a cancel or a blocked requirement still do. A `cancelled` run is never derived: the
    cancel sets it."""
    statuses = list(tasks)
    if statuses and all(s == AssessmentTaskStatus.QUEUED for s in statuses):
        return AssessmentRunStatus.QUEUED
    if any(s in TASK_IN_PROGRESS for s in statuses):
        return AssessmentRunStatus.RUNNING
    succeeded = sum(1 for s in statuses if s == AssessmentTaskStatus.SUCCEEDED)
    skipped = sum(1 for s in statuses if s == AssessmentTaskStatus.SKIPPED)
    chosen = max(0, min(chosen_skips, skipped))
    if succeeded == len(statuses):
        return AssessmentRunStatus.SUCCEEDED
    if succeeded == 0:
        return AssessmentRunStatus.FAILED
    if succeeded + chosen == len(statuses):
        return AssessmentRunStatus.SUCCEEDED
    return AssessmentRunStatus.PARTIALLY_FAILED


def chosen_skip(status: AssessmentTaskStatus, skip_reason: str | None) -> bool:
    """A task skipped because a person chose to continue without its Agent (Story 5.5)."""
    return (
        status == AssessmentTaskStatus.SKIPPED
        and skip_reason == TaskSkipReason.AGENT_DISABLED.value
    )


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
    """The run paused on an open decision (Story 5.5); one row per open decision."""


PROGRESS_RETENTION_DAYS = 30
"""Progress rows older than this are pruned (they are not audit records)."""


def task_summary(agent: str, status: AssessmentTaskStatus) -> str:
    """A progress row's summary for a task: its Agent id and status, never customer text."""
    return f"{agent} {status.value}"


def run_summary(status: AssessmentRunStatus) -> str:
    return f"run {status.value}"


def waiting_summary(agent: str) -> str:
    """A waiting row's summary: the Agent whose decision the run waits on."""
    return f"{agent} {AssessmentRunStatus.WAITING_FOR_HUMAN.value}"
