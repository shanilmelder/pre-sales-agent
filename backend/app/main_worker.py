"""`worker` process entry point: jobs only (AD-1, AD-7, AD-29).

Claims jobs from `platform_jobs` one at a time and runs them; when no job is ready it sleeps
for a short jittered poll. On SIGINT/SIGTERM it stops claiming, cancels the current
job and releases it back to the queue without counting the attempt (a worker killed
outright has its job reclaimed by another worker once the lease expires).

Job types are registered by importing the modules that define them (see `_JOB_MODULES`).
"""

import asyncio
import contextlib
import importlib
import os
import random
import signal
import socket
import sys
from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.config import Settings, get_settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.jobs import REGISTRY
from app.platform.jobs import queue as job_queue
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.logging import configure_logging, get_logger

_log = get_logger("app.worker")

# Modules whose import registers job types (e.g. `app.modules.intake.application.jobs`).
_JOB_MODULES: tuple[str, ...] = ("app.modules.intake.application.jobs",)
_JITTER = 0.2


def load_job_types() -> None:
    for name in _JOB_MODULES:
        importlib.import_module(name)


def worker_id() -> str:
    """Unique per process start, so a restarted worker never mistakes an old claim for its own."""
    return f"{socket.gethostname()}:{os.getpid()}:{new_id().hex[-8:]}"


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _run_until_stopped(
    db: AsyncEngine, job: job_queue.ClaimedJob, lease: LeaseSettings, stop: asyncio.Event
) -> None:
    """Run one job; if `stop` fires first, cancel it so the runner releases the job back to
    the queue (attempt not counted) instead of Docker killing it mid-run."""
    work = asyncio.create_task(run_job(db, job, lease))
    stopper = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({work, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopper.cancel()
        if not work.done():
            work.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work
            _log.info("worker.job_abandoned", extra={"job_id": str(job.id)})
    if not work.cancelled():
        work.result()  # re-raise a runner error for the caller to log


async def run(
    stop: asyncio.Event,
    *,
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    poll_s: float | None = None,
    job_types: Collection[str] | None = None,
) -> None:
    """Claim and run jobs until `stop` is set.

    `job_types` limits what this worker claims (default: every registered type). An engine
    passed in is left open; one created here is disposed on exit."""
    settings = settings or get_settings()
    poll = poll_s if poll_s is not None else settings.worker_poll_s
    types = frozenset(REGISTRY) if job_types is None else frozenset(job_types)
    lease = LeaseSettings(lease_s=settings.job_lease_s, heartbeat_s=settings.job_heartbeat_s)
    owner = worker_id()
    own_engine = engine is None
    db = engine if engine is not None else create_engine(settings)
    _log.info(
        "worker.started",
        extra={
            "version": settings.version,
            "env": settings.env,
            "worker_id": owner,
            "job_types": sorted(types),
        },
    )
    try:
        while not stop.is_set():
            try:
                job = await job_queue.claim(db, owner=owner, lease_s=lease.lease_s, job_types=types)
            except Exception as exc:  # DB down: log, back off, try again
                _log.warning("worker.claim_failed", extra={"exc_type": type(exc).__name__})
                job = None
            if job is not None:
                try:
                    await _run_until_stopped(db, job, lease, stop)
                except Exception as exc:  # e.g. DB down while finishing: the lease expires
                    _log.warning(  # and another claim retries the job
                        "worker.job_error",
                        extra={"job_id": str(job.id), "exc_type": type(exc).__name__},
                    )
                    await _sleep_or_stop(stop, poll)
                continue
            jitter = random.uniform(1 - _JITTER, 1 + _JITTER)  # noqa: S311 (not crypto)
            await _sleep_or_stop(stop, poll * jitter)
    finally:
        if own_engine:
            await db.dispose()
        _log.info("worker.stopped", extra={"worker_id": owner})


async def _main() -> None:
    stop = asyncio.Event()
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    load_job_types()
    await run(stop)


def main() -> None:
    configure_logging(get_settings().log_level)
    # psycopg's async driver cannot use the Windows Proactor loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        asyncio.run(_main(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        _log.info("worker.stopped")


if __name__ == "__main__":
    main()
