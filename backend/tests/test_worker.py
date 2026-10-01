import asyncio
import logging

import pytest

from app.main_worker import run


def test_worker_logs_start_and_stops(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(run(stop, idle_s=0.01))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(scenario())
    events = [r.getMessage() for r in caplog.records if r.name == "app.worker"]
    assert events == ["worker.started", "worker.stopped"]
