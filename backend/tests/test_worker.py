"""The worker loop without a database: start, idle and stop (no job types to claim).

Claiming and running jobs against Postgres is covered in tests/test_jobs.py."""

import asyncio
import logging
import time

import pytest

from app.main_worker import run
from app.platform.config import Settings
from tests.conftest import UNREACHABLE_DB, run_async


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
