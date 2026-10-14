"""The worker loop without a database: start, idle and stop (no job types to claim); and,
against Postgres (Story 5.2), running a Workflow Run with the graph runner the worker
installs itself, and enqueueing a due schedule's job.

Claiming and running jobs against Postgres is otherwise covered in tests/test_jobs.py."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.main_worker import run
from app.modules.workflows.application import public as workflows
from app.modules.workflows.application import runs as workflows_runs
from app.platform.config import Settings
from tests import test_orchestration as orchestration_tests
from tests.conftest import UNREACHABLE_DB, run_async
from tests.test_gaps_detection import rows
from tests.test_intake_extraction import FakeGateway, owner
from tests.test_orchestration import FixtureExecutor, planned, run_row


def test_worker_logs_start_and_stops(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        settings = Settings(database_url=UNREACHABLE_DB)
        task = asyncio.create_task(run(stop, settings=settings, poll_s=0.01, job_types=()))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    with caplog.at_level(logging.INFO, logger="app.worker"):
        run_async(scenario())
    events = [r.getMessage() for r in caplog.records if r.name == "app.worker"]
    assert events == ["worker.started", "worker.stopped"]


def test_worker_keeps_its_alive_file_fresh_while_running(tmp_path: Path) -> None:
    alive = tmp_path / "worker-alive"

    async def scenario() -> list[float]:
        stop = asyncio.Event()
        settings = Settings(database_url=UNREACHABLE_DB, worker_alive_file=alive)
        task = asyncio.create_task(
            run(stop, settings=settings, poll_s=0.01, job_types=(), alive_interval_s=0.05)
        )
        await asyncio.sleep(0.1)
        first = alive.stat().st_mtime_ns
        await asyncio.sleep(0.2)
        second = alive.stat().st_mtime_ns
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        return [first, second]

    first, second = run_async(scenario())
    assert second > first  # touched again while running


def test_worker_without_an_alive_file_writes_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        settings = Settings(database_url=UNREACHABLE_DB)
        task = asyncio.create_task(
            run(stop, settings=settings, poll_s=0.01, job_types=(), alive_interval_s=0.01)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    run_async(scenario())
    assert list(tmp_path.iterdir()) == []


def test_worker_stops_within_one_poll_interval_when_idle() -> None:
    async def scenario() -> float:
        stop = asyncio.Event()
        settings = Settings(database_url=UNREACHABLE_DB)
        task = asyncio.create_task(run(stop, settings=settings, poll_s=0.5, job_types=()))
        await asyncio.sleep(0.05)
        started = time.monotonic()
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return time.monotonic() - started

    assert run_async(scenario()) < 0.5


def test_worker_keeps_running_when_the_database_is_down(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        settings = Settings(database_url=UNREACHABLE_DB, db_connect_timeout_s=1)
        task = asyncio.create_task(
            run(stop, settings=settings, poll_s=0.01, job_types=("testworker.noop",))
        )
        for _ in range(500):
            await asyncio.sleep(0.01)
            if any(r.getMessage() == "worker.claim_failed" for r in caplog.records):
                break
        assert not task.done()
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    with caplog.at_level(logging.INFO, logger="app.worker"):
        run_async(scenario())
    assert "worker.claim_failed" in [r.getMessage() for r in caplog.records]


def test_settings_require_the_heartbeat_at_most_half_the_lease() -> None:
    with pytest.raises(ValueError, match="job_heartbeat_s"):
        Settings(job_lease_s=10, job_heartbeat_s=5.1)
    assert Settings(job_lease_s=10, job_heartbeat_s=5).job_heartbeat_s == 5


def test_worker_installs_its_gateway_while_running() -> None:
    from app.platform.model_gateway import provider

    class Fake:
        async def complete_structured(self, request: object) -> object:
            raise AssertionError("not called")

    fake = Fake()

    async def scenario() -> object:
        stop = asyncio.Event()
        settings = Settings(database_url=UNREACHABLE_DB)
        task = asyncio.create_task(
            run(stop, settings=settings, poll_s=0.01, job_types=(), gateway=fake)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.05)
        during = provider.current()
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        return during

    assert run_async(scenario()) is fake
    with pytest.raises(provider.NoModelGatewayError):
        provider.current()


# --- with a database (Story 5.2) ------------------------------------------------------------

storage_dir = orchestration_tests.storage_dir
_hidden_jobs = orchestration_tests._hidden_jobs
gateway = orchestration_tests.gateway
client = orchestration_tests.client
fixtures = orchestration_tests.fixtures


async def _until(check: Callable[[], bool], timeout_s: float = 30) -> None:
    async with asyncio.timeout(timeout_s):
        while not await asyncio.to_thread(check):  # noqa: ASYNC110 - polls the database
            await asyncio.sleep(0.1)


def test_the_worker_installs_the_graph_runner_and_runs_a_workflow_run(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fixtures: dict[str, FixtureExecutor],
) -> None:
    workflows.install_runner(None)  # not the conftest's: the worker must install its own
    _, opp = owner(client, sync_engine)
    run_id, _ = planned(db_url, opp["id"], hold=False)

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run(
                stop,
                settings=Settings(database_url=db_url),
                poll_s=0.05,
                job_types=("workflows.execute",),
                gateway=gateway,  # type: ignore[arg-type]
            )
        )
        try:
            await _until(lambda: run_row(sync_engine, run_id)["status"] == "succeeded")
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=10)

    run_async(scenario())

    assert run_row(sync_engine, run_id)["status"] == "succeeded"
    assert all(len(f.accepted) == 1 for f in fixtures.values())
    with pytest.raises(workflows.NoGraphRunnerError):  # removed again on exit
        workflows_runs.current_runner()


def test_the_worker_enqueues_a_due_schedule(sync_engine: Engine, db_url: str) -> None:
    since = datetime.now(UTC)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE platform_schedules SET next_run_at = now() - interval '1 minute' "
                "WHERE name = 'workflows.prune_progress'"
            )
        )

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run(
                stop,
                settings=Settings(database_url=db_url),
                poll_s=0.05,
                job_types=("workflows.prune_progress",),
                gateway=object(),  # type: ignore[arg-type]
            )
        )
        try:
            await _until(
                lambda: bool(
                    rows(
                        sync_engine,
                        "SELECT id FROM platform_jobs WHERE job_type = "
                        "'workflows.prune_progress' AND created_at >= :s",
                        s=since,
                    )
                )
            )
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=10)

    run_async(scenario())

    (schedule,) = rows(
        sync_engine, "SELECT * FROM platform_schedules WHERE name = 'workflows.prune_progress'"
    )
    assert schedule["next_run_at"] > since
    with sync_engine.begin() as conn:  # nothing else ever runs a job left queued
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead', last_error = 'test: not run' "
                "WHERE job_type = 'workflows.prune_progress' AND status = 'queued'"
            )
        )
