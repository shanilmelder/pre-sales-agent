"""Workflow Run rules (Story 5.2), without a database: the run status from its tasks' (moved
from the assessments domain tests), whether a task may start given the tasks it requires,
and the progress summaries."""

from uuid import uuid4

import pytest

from app.modules.workflows.domain.runs import (
    TASK_AGENTS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    readiness,
    run_status,
    task_agent_rank,
    task_summary,
)

Q, R, S, F, K = (
    AssessmentTaskStatus.QUEUED,
    AssessmentTaskStatus.RUNNING,
    AssessmentTaskStatus.SUCCEEDED,
    AssessmentTaskStatus.FAILED,
    AssessmentTaskStatus.SKIPPED,
)


@pytest.mark.parametrize(
    ("tasks", "expected"),
    [
        ((Q, Q, Q), AssessmentRunStatus.QUEUED),
        ((S, Q, Q), AssessmentRunStatus.RUNNING),
        ((R, S, F), AssessmentRunStatus.RUNNING),
        ((S, S, S), AssessmentRunStatus.SUCCEEDED),
        ((S, F, S), AssessmentRunStatus.PARTIALLY_FAILED),
        ((S, K, S), AssessmentRunStatus.PARTIALLY_FAILED),
        ((F, F, F), AssessmentRunStatus.FAILED),
    ],
)
def test_the_run_status_follows_its_tasks(
    tasks: tuple[AssessmentTaskStatus, ...], expected: AssessmentRunStatus
) -> None:
    assert run_status(tasks) is expected


def test_a_task_requiring_nothing_is_ready() -> None:
    assert readiness((), {}) == "ready"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((S, S), "ready"),
        ((S, Q), "waiting"),
        ((R, S), "waiting"),
        ((S, F), "blocked"),
        ((K, Q), "blocked"),
    ],
)
def test_a_task_waits_for_every_task_it_requires(
    statuses: tuple[AssessmentTaskStatus, ...], expected: str
) -> None:
    ids = [uuid4() for _ in statuses]
    assert readiness(ids, dict(zip(ids, statuses, strict=True))) == expected


def test_a_required_task_outside_the_run_is_ignored() -> None:
    assert readiness((uuid4(),), {}) == "ready"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((S, S, S), "ready"),
        ((S, F, K), "ready"),  # ended, whatever the outcome
        ((F, F, F), "ready"),
        ((S, R, S), "waiting"),
        ((Q, F, S), "waiting"),
    ],
)
def test_a_task_runs_after_every_task_has_ended_whatever_the_outcome(
    statuses: tuple[AssessmentTaskStatus, ...], expected: str
) -> None:
    """Story 6.4: the Critic's task runs `after` the specialists'."""
    ids = [uuid4() for _ in statuses]
    assert readiness((), dict(zip(ids, statuses, strict=True)), ids) == expected


def test_requires_and_after_combine() -> None:
    required, later = uuid4(), uuid4()
    assert readiness((required,), {required: F, later: S}, (later,)) == "blocked"
    assert readiness((required,), {required: S, later: R}, (later,)) == "waiting"
    assert readiness((required,), {required: S, later: F}, (later,)) == "ready"
    assert readiness((), {}, (uuid4(),)) == "ready"  # outside the run: ignored


def test_the_critic_is_planned_last() -> None:
    assert [a.value for a in TASK_AGENTS] == [
        "engineering_agent",
        "pm_agent",
        "security_agent",
        "critic_agent",
    ]
    assert task_agent_rank("critic_agent") == 3
    assert task_agent_rank("red_team_agent") == 4


def test_progress_summaries_carry_agent_ids_and_statuses_only() -> None:
    assert task_summary("pm_agent", R) == "pm_agent running"
