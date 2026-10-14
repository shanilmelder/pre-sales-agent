"""Workflow Run rules (Story 5.2), without a database: the run status from its tasks' (moved
from the assessments domain tests), whether a task may start given the tasks it requires,
and the progress summaries."""

from uuid import uuid4

import pytest

from app.modules.workflows.domain.runs import (
    AssessmentRunStatus,
    AssessmentTaskStatus,
    readiness,
    run_status,
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


def test_progress_summaries_carry_agent_ids_and_statuses_only() -> None:
    assert task_summary("pm_agent", R) == "pm_agent running"
