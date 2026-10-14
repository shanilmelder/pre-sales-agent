"""Durable LangGraph execution of Workflow Runs (Story 5.2) against a real, migrated
Postgres as psa_app, with test-only fixture executors (the node wrapper calls them in place of
the specialist Agents and `assessments.accept_assessment`):

- three independent tasks run concurrently; the run's checkpoints (`thread_id = run_id`)
  live in `orchestration_checkpoints` and hold ids only;
- `requires`: a task starts only after the tasks it requires succeeded, and is skipped when
  one of them failed;
- a crash mid-run (the job abandoned without any cleanup, then claimed again) resumes the
  thread: a node that finished is not run again and nothing is accepted twice;
- a task already `succeeded` in the database whose node the checkpoint lacks is not re-run;
- a job retry re-runs only the failed task.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.registry.domain.registry import seed_config_version_id
from app.modules.workflows.adapters import repository as workflows_repo
from app.modules.workflows.adapters.repository import NewTask
from app.modules.workflows.application import public as workflows_public
from app.modules.workflows.application import runs as workflows_runs
from app.modules.workflows.application.public import NodeTask
from app.orchestration import executors as orchestration_executors
from app.orchestration import graph as orchestration_graph
from app.orchestration.checkpointer import open_checkpointer
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.jobs import JobContext, enqueue
from app.platform.model_gateway.port import ModelUnavailableError
from app.platform.uow import UnitOfWork, unit_of_work
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_gaps_detection import rows
from tests.test_intake_extraction import ASSESS, FakeGateway, drain, owner

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

ENGINEERING, PM, SECURITY = "engineering_agent", "pm_agent", "security_agent"
AGENTS = (ENGINEERING, PM, SECURITY)


class FixtureExecutor:
    """A test-only executor: `run` sleeps (or waits for `gate`), then answers from `replies`
    in order (the last one repeats; an exception is raised); `accept` only records the task.
    It counts each step and records each run's time window."""

    def __init__(self, *, replies: Sequence[Exception | None] = (None,), delay_s: float = 0.2):
        self.replies = list(replies)
        self.delay_s = delay_s
        self.prepared = 0
        self.runs = 0
        self.accepted: list[UUID] = []
        self.windows: list[tuple[float, float]] = []
        self.gated = False
        self.gate: asyncio.Event | None = None
        self.started: asyncio.Event | None = None

    async def prepare(self, uow: UnitOfWork, task: NodeTask) -> NodeTask:
        self.prepared += 1
        return task

    async def run(self, prepared: NodeTask) -> dict[str, str]:
        self.runs += 1
        began = time.monotonic()
        if self.started is not None:
            self.started.set()
        if self.gated:
            self.gate = self.gate or asyncio.Event()
            await self.gate.wait()
        await asyncio.sleep(self.delay_s)
        self.windows.append((began, time.monotonic()))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if reply is not None:
            raise reply
        return {"task_id": str(prepared.id)}

    async def accept(
        self, uow: UnitOfWork, task: NodeTask, prepared: NodeTask, result: dict[str, str]
    ) -> None:
        assert result == {"task_id": str(task.id)}
        self.accepted.append(task.id)


@pytest.fixture
def fixtures(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, FixtureExecutor]]:
    """A fixture executor in place of each specialist Agent's."""
    found = {agent: FixtureExecutor() for agent in AGENTS}
    for agent, executor in found.items():
        monkeypatch.setitem(orchestration_executors.EXECUTORS, agent, executor)
    yield found


def planned(
    db_url: str,
    opp_id: str,
    requires: Mapping[str, Sequence[str]] | None = None,
    *,
    hold: bool = True,
) -> tuple[UUID, dict[str, UUID]]:
    """A queued run of the Opportunity with one task per specialist Agent (`requires` by
    agent) and its job, held back a day (unless not `hold`) so only this test's `drain`
    runs it."""
    requires = requires or {}

    async def scenario() -> tuple[UUID, dict[str, UUID]]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                ids = {agent: new_id() for agent in AGENTS}
                run_id = new_id()
                await workflows_repo.insert_run(
                    uow,
                    run_id=run_id,
                    opportunity_id=UUID(opp_id),
                    tasks=[
                        NewTask(
                            id=ids[agent],
                            agent=agent,
                            config_version_id=seed_config_version_id(agent),
                            requires=tuple(ids[r] for r in requires.get(agent, ())),
                        )
                        for agent in AGENTS
                    ],
                    plan_version=1,
                )
                await enqueue(
                    uow,
                    workflows_runs.ExecuteRun(run_id=run_id),
                    opportunity_id=UUID(opp_id),
                    run_after=datetime.now(UTC) + timedelta(days=1) if hold else None,
                )
            return run_id, ids
        finally:
            await engine.dispose()

    return run_async(scenario())


def run_row(engine: Engine, run_id: UUID) -> dict[str, Any]:
    (row,) = rows(engine, "SELECT * FROM workflows_runs WHERE id = :r", r=run_id)
    return row


def task_rows(engine: Engine, run_id: UUID) -> dict[str, dict[str, Any]]:
    return {
        r["agent"]: r
        for r in rows(engine, "SELECT * FROM workflows_tasks WHERE run_id = :r", r=run_id)
    }


def progress_rows(engine: Engine, run_id: UUID) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM workflows_progress WHERE run_id = :r ORDER BY id", r=run_id)


def checkpoint(db_url: str, run_id: UUID) -> Any:
    """The latest checkpoint tuple of the run's thread (None if there is none)."""

    async def scenario() -> Any:
        async with open_checkpointer(db_url, setup=False) as saver:
            return await saver.aget_tuple({"configurable": {"thread_id": str(run_id)}})

    return run_async(scenario())


def _accepted(found: dict[str, FixtureExecutor]) -> int:
    return len(found[ENGINEERING].accepted) + len(found[SECURITY].accepted)


def _is_id(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


# --- the happy path -------------------------------------------------------------------------


def test_independent_tasks_run_concurrently_and_the_checkpoint_holds_ids_only(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
) -> None:
    _, opp = owner(client, sync_engine)
    for executor in fixtures.values():
        executor.delay_s = 0.5
    run_id, ids = planned(db_url, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    assert run_row(sync_engine, run_id)["status"] == "succeeded"
    assert {t["status"] for t in task_rows(sync_engine, run_id).values()} == {"succeeded"}
    windows = [fixtures[agent].windows[0] for agent in AGENTS]
    assert max(start for start, _ in windows) < min(end for _, end in windows)  # overlapping
    assert {agent: fixtures[agent].accepted for agent in AGENTS} == {
        agent: [ids[agent]] for agent in AGENTS
    }

    saved = checkpoint(db_url, run_id)
    assert saved is not None
    values = saved.checkpoint["channel_values"]
    assert values["run_id"] == str(run_id)
    assert sorted(values["finished"]) == sorted(str(i) for i in ids.values())
    for key, value in values.items():  # ids only: no customer content can be in there
        flat = value if isinstance(value, list) else [value]
        assert all(v is None or (isinstance(v, str) and _is_id(v)) for v in flat), key
    with sync_engine.connect() as conn:
        threads = conn.execute(
            sa.text(
                "SELECT count(*) FROM orchestration_checkpoints.checkpoints WHERE thread_id = :t"
            ),
            {"t": str(run_id)},
        ).scalar_one()
    assert threads >= 2  # one per superstep

    events = [(r["event_type"], r["summary"]) for r in progress_rows(sync_engine, run_id)]
    assert (
        sorted(e for e, _ in events if e.startswith("workflows.task"))
        == ["workflows.task.ended"] * 3 + ["workflows.task.started"] * 3
    )
    assert events[-1] == ("workflows.run.ended", "run succeeded")
    assert ("workflows.task.ended", "pm_agent succeeded") in events


# --- requires -------------------------------------------------------------------------------


def test_a_task_starts_only_after_the_task_it_requires_succeeded(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
) -> None:
    _, opp = owner(client, sync_engine)
    run_id, ids = planned(db_url, opp["id"], requires={PM: [ENGINEERING]})

    assert drain(db_url, ASSESS) == ["succeeded"]

    (engineering_window,) = fixtures[ENGINEERING].windows
    (pm_window,) = fixtures[PM].windows
    assert pm_window[0] >= engineering_window[1]  # B started after A ended
    tasks = task_rows(sync_engine, run_id)
    assert tasks[PM]["requires"] == [ids[ENGINEERING]]
    assert tasks[PM]["started_at"] >= tasks[ENGINEERING]["finished_at"]
    assert run_row(sync_engine, run_id)["status"] == "succeeded"


def test_a_task_whose_required_task_failed_never_runs(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
) -> None:
    _, opp = owner(client, sync_engine)
    fixtures[ENGINEERING].replies = [ModelUnavailableError("down", error_code="connection")]
    run_id, _ = planned(db_url, opp["id"], requires={PM: [ENGINEERING]})

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    assert fixtures[PM].prepared == fixtures[PM].runs == 0
    assert fixtures[ENGINEERING].runs == 2  # once per attempt
    assert fixtures[SECURITY].runs == 1  # succeeded on the first attempt, not re-run
    tasks = task_rows(sync_engine, run_id)
    assert (tasks[ENGINEERING]["status"], tasks[ENGINEERING]["error_code"]) == (
        "failed",
        "model_unavailable",
    )
    assert (tasks[PM]["status"], tasks[PM]["started_at"]) == ("skipped", None)
    assert tasks[SECURITY]["status"] == "succeeded"
    assert run_row(sync_engine, run_id)["status"] == "partially_failed"


# --- durability -----------------------------------------------------------------------------


def crash(
    engine: Engine,
    db_url: str,
    opp_id: str,
    run_id: UUID,
    fixtures: dict[str, FixtureExecutor],
    ready: Callable[[], bool],
) -> None:
    """Run the run's job (attempt 1 of 2) until the gated PM task has started and `ready()`,
    then kill it: the handler is cancelled and records nothing."""
    (job,) = rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
        t=ASSESS,
        o=opp_id,
    )

    async def scenario() -> None:
        db = create_engine(Settings(database_url=db_url))
        fixtures[PM].started = asyncio.Event()
        try:
            ctx = JobContext(
                job_id=job["id"],
                job_type=ASSESS,
                attempt=1,
                max_attempts=2,
                opportunity_id=UUID(opp_id),
                engine=db,
            )
            handler = asyncio.create_task(
                workflows_runs.execute_run(ctx, workflows_runs.ExecuteRun(run_id=run_id))
            )
            async with asyncio.timeout(10):
                await fixtures[PM].started.wait()
                while not ready():  # noqa: ASYNC110 - plain counters
                    await asyncio.sleep(0.05)
            await asyncio.sleep(0.5)  # the finished nodes' writes reach the checkpointer
            handler.cancel()  # the worker is killed: nothing records anything
            with pytest.raises(asyncio.CancelledError):
                await handler
        finally:
            await db.dispose()

    run_async(scenario())


def test_a_crash_mid_run_resumes_the_thread_without_rerunning_finished_nodes(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, opp = owner(client, sync_engine)
    run_id, ids = planned(db_url, opp["id"])
    fixtures[PM].gated = True  # PM hangs until the worker "dies"

    crash(sync_engine, db_url, opp["id"], run_id, fixtures, lambda: _accepted(fixtures) >= 2)

    tasks = task_rows(sync_engine, run_id)
    assert (tasks[ENGINEERING]["status"], tasks[PM]["status"]) == ("succeeded", "running")
    saved = checkpoint(db_url, run_id)
    assert saved is not None
    finished_writes = [v for _, channel, v in saved.pending_writes if channel == "finished"]
    assert sorted(finished_writes) == sorted([[str(ids[ENGINEERING])], [str(ids[SECURITY])]])

    fixtures[PM].gated = False
    fixtures[PM].gate = None
    caplog.clear()  # only what the reclaimed job logs
    with caplog.at_level(logging.INFO):
        assert drain(db_url, ASSESS) == ["succeeded"]  # the job, reclaimed

    resumed = [r for r in caplog.records if r.getMessage() == "orchestration.run_resumed"]
    assert len(resumed) == 1
    entered = {
        getattr(r, "task_id", None)
        for r in caplog.records
        if r.getMessage() == "orchestration.node_entered"
    }
    assert entered == {str(ids[PM])}  # only the unfinished node ran again
    assert (fixtures[ENGINEERING].runs, fixtures[SECURITY].runs, fixtures[PM].runs) == (1, 1, 2)
    assert {agent: fixtures[agent].accepted for agent in AGENTS} == {
        agent: [ids[agent]] for agent in AGENTS
    }  # nothing accepted twice
    assert run_row(sync_engine, run_id)["status"] == "succeeded"


def test_a_crash_after_a_task_failed_on_an_earlier_attempt_runs_it_again(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Security fails (not the final attempt: its node ends, its task stays `running`), then
    the worker dies while PM is mid-call. A resume would never run Security's node again, so
    the reclaimed job starts a fresh invocation on the thread instead."""
    _, opp = owner(client, sync_engine)
    run_id, ids = planned(db_url, opp["id"])
    fixtures[SECURITY].replies = [ModelUnavailableError("down", error_code="connection"), None]
    fixtures[PM].gated = True

    crash(
        sync_engine,
        db_url,
        opp["id"],
        run_id,
        fixtures,
        lambda: len(fixtures[ENGINEERING].accepted) == 1 and len(fixtures[SECURITY].windows) == 1,
    )

    tasks = task_rows(sync_engine, run_id)
    assert (tasks[SECURITY]["status"], tasks[PM]["status"]) == ("running", "running")
    fixtures[PM].gated = False
    fixtures[PM].gate = None
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert drain(db_url, ASSESS) == ["succeeded"]  # no extra attempt needed

    messages = [r.getMessage() for r in caplog.records]
    assert "orchestration.run_invoked" in messages
    assert "orchestration.run_resumed" not in messages
    assert (fixtures[ENGINEERING].runs, fixtures[SECURITY].runs, fixtures[PM].runs) == (1, 2, 2)
    assert {agent: fixtures[agent].accepted for agent in AGENTS} == {
        agent: [ids[agent]] for agent in AGENTS
    }
    assert run_row(sync_engine, run_id)["status"] == "succeeded"


def test_a_final_attempt_fails_a_task_whose_node_could_not_record_its_outcome(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security's call fails on both attempts and, on the final one, marking it `failed`
    fails too: the handler's fallback fails the unfinished task and finishes the run."""
    _, opp = owner(client, sync_engine)
    run_id, _ = planned(db_url, opp["id"])
    fixtures[SECURITY].replies = [ModelUnavailableError("down", error_code="connection")]
    real_fail = workflows_public.fail_task

    async def broken(uow: UnitOfWork, task_id: UUID, error_code: str) -> bool:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(workflows_public, "fail_task", broken)

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    assert real_fail is not broken
    tasks = task_rows(sync_engine, run_id)
    assert (tasks[SECURITY]["status"], tasks[SECURITY]["error_code"]) == (
        "failed",
        "model_unavailable",
    )
    assert {tasks[a]["status"] for a in (ENGINEERING, PM)} == {"succeeded"}
    assert run_row(sync_engine, run_id)["status"] == "partially_failed"


def test_a_task_accepted_but_not_checkpointed_is_not_run_again(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
) -> None:
    _, opp = owner(client, sync_engine)
    run_id, ids = planned(db_url, opp["id"])
    with sync_engine.begin() as conn:  # accepted and committed; the checkpoint never saw it
        conn.execute(
            sa.text(
                "UPDATE workflows_tasks SET status = 'succeeded', started_at = now(), "
                "finished_at = now() WHERE id = :t"
            ),
            {"t": ids[ENGINEERING]},
        )

    assert drain(db_url, ASSESS) == ["succeeded"]

    assert fixtures[ENGINEERING].prepared == fixtures[ENGINEERING].runs == 0
    assert fixtures[ENGINEERING].accepted == []
    assert (fixtures[PM].runs, fixtures[SECURITY].runs) == (1, 1)
    assert run_row(sync_engine, run_id)["status"] == "succeeded"


def test_a_job_retry_reruns_only_the_failed_task(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
) -> None:
    _, opp = owner(client, sync_engine)
    fixtures[SECURITY].replies = [ModelUnavailableError("down", error_code="connection"), None]
    run_id, _ = planned(db_url, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "succeeded"]

    assert (fixtures[ENGINEERING].runs, fixtures[PM].runs, fixtures[SECURITY].runs) == (1, 1, 2)
    assert all(len(f.accepted) == 1 for f in fixtures.values())
    assert run_row(sync_engine, run_id)["status"] == "succeeded"


def test_a_manual_retry_runs_only_the_requeued_task_on_the_same_thread(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, opp = owner(client, sync_engine)
    down = ModelUnavailableError("down", error_code="connection")
    fixtures[SECURITY].replies = [down, down, None]
    run_id, ids = planned(db_url, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    assert run_row(sync_engine, run_id)["status"] == "partially_failed"
    first = checkpoint(db_url, run_id)
    assert first is not None

    async def retry() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await workflows_repo.lock_runs(uow, UUID(opp["id"]))
                run = await workflows_repo.get_run(uow, run_id, for_update=True)
                assert run is not None
                await workflows_runs.requeue_task(uow, run, SECURITY, workflows_runs.SYSTEM)
        finally:
            await engine.dispose()

    run_async(retry())
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert drain(db_url, ASSESS) == ["succeeded"]

    assert [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("orchestration.run_")
    ][:1] == ["orchestration.run_invoked"]  # a fresh invocation, not a resume
    assert (fixtures[ENGINEERING].runs, fixtures[PM].runs, fixtures[SECURITY].runs) == (1, 1, 3)
    assert {agent: fixtures[agent].accepted for agent in AGENTS} == {
        agent: [ids[agent]] for agent in AGENTS
    }
    assert run_row(sync_engine, run_id)["status"] == "succeeded"
    latest = checkpoint(db_url, run_id)  # the same thread, moved on
    assert latest is not None
    assert latest.config["configurable"]["thread_id"] == str(run_id)
    assert latest.checkpoint["id"] != first.checkpoint["id"]


def test_a_graph_builds_whatever_order_its_plan_lists_the_tasks_in() -> None:
    """A task may be listed before the task it requires (plans come in id order)."""
    first, second, third = new_id(), new_id(), new_id()
    run = workflows_runs.GraphRun(
        run_id=new_id(),
        opportunity_id=new_id(),
        engine=None,  # type: ignore[arg-type] - never invoked
        attempt=1,
        max_attempts=2,
    )
    plan = [(first, (third,)), (second, ()), (third, (second,))]

    graph = orchestration_graph.build_graph(plan, orchestration_graph.Invocation(run=run), None)

    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    name = orchestration_graph.node_name
    assert ("__start__", name(second)) in edges
    assert (name(second), name(third)) in edges
    assert (name(third), name(first)) in edges
    assert (name(first), "__end__") in edges
