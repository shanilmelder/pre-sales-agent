"""`worker` process entry point: jobs only (AD-1, AD-7, AD-29).

Claims jobs from `platform_jobs` one at a time and runs them; when no job is ready it sleeps
for a short jittered poll. On SIGINT/SIGTERM it stops claiming, cancels the current
job and releases it back to the queue without counting the attempt (a worker killed
outright has its job reclaimed by another worker once the lease expires).

Job types are registered by importing the modules that define them (see `_JOB_MODULES`).
The process's ModelGateway (one per process: its semaphore bounds concurrent model calls) is
created here and installed for handlers (`app.platform.model_gateway.provider`).

Story 5.2: the worker also opens the LangGraph checkpointer's connection pool and installs
the graph runner (`app.orchestration.runner`) as `workflows`' runner hook, so only this
process builds and runs graphs; and, about once a minute, enqueues the jobs of due
`platform_schedules` (e.g. the daily progress prune).
"""

import asyncio
import contextlib
import importlib
import os
import random
import signal
import socket
import sys
import time
from collections.abc import AsyncIterator, Collection
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.config import Settings, get_settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.jobs import REGISTRY
from app.platform.jobs import queue as job_queue
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.logging import configure_logging, get_logger
from app.platform.model_gateway import provider as model_gateway
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import ModelGatewayPort
from app.platform.schedules import enqueue_due

_log = get_logger("app.worker")

# Modules whose import registers job types (e.g. `app.modules.intake.application.jobs`).
_JOB_MODULES: tuple[str, ...] = (
    "app.modules.intake.application.jobs",
    "app.modules.knowledge.application.jobs",
    "app.modules.intake.application.extraction",
    "app.modules.gaps.application.detection",
    "app.modules.gaps.application.answer_matching",
    "app.modules.estimates.application.draft",
    "app.modules.estimates.application.assumptions",
    "app.modules.assessments.application.review",
    "app.modules.conflicts.application.semantic",
    "app.modules.workflows.application.runs",
    "app.modules.workflows.application.progress",
    "app.modules.opportunities.application.imports",
    "app.platform.alerts.jobs",
)
_JITTER = 0.2
EXECUTE_JOB_TYPE = "workflows.execute"
GRAPH_JOB_TYPES = frozenset({EXECUTE_JOB_TYPE, "workflows.resume"})
"""The job types whose handler runs a graph (Story 5.2; resume, Story 5.5)."""
SCHEDULE_CHECK_S = 60.0
"""How often the poll loop enqueues the jobs of due schedules."""


def load_job_types() -> None:
    for name in _JOB_MODULES:
        importlib.import_module(name)


def worker_id() -> str:
    """Unique per process start, so a restarted worker never mistakes an old claim for its own."""
    return f"{socket.gethostname()}:{os.getpid()}:{new_id().hex[-8:]}"


ALIVE_INTERVAL_S = 10.0
"""How often the worker touches its alive file. The compose healthcheck allows 60 s."""


async def _keep_alive(path: Path, stop: asyncio.Event, interval_s: float) -> None:
    """Touch `path` every `interval_s` until `stop` is set. It runs on the event loop, so a
    blocked loop (a hung worker) stops touching it and the container turns unhealthy."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(path.touch)
        except OSError as exc:
            _log.warning("worker.alive_file_failed", extra={"exc_type": type(exc).__name__})
        await _sleep_or_stop(stop, interval_s)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _enqueue_schedules(db: AsyncEngine, job_types: Collection[str]) -> None:
    if not job_types:
        return
    try:
        await enqueue_due(db, job_types)
    except Exception as exc:  # DB down: try again at the next check
        _log.warning("worker.schedules_failed", extra={"exc_type": type(exc).__name__})


@contextlib.asynccontextmanager
async def _graph_runner(settings: Settings, install: bool) -> AsyncIterator[None]:
    """Open the checkpointer's pool and install the graph runner for handlers (Story 5.2);
    removed and closed on exit. Imported here: only the worker loads `app.orchestration`
    (and so `langgraph`)."""
    if not install:
        yield
        return
    from app.modules.workflows.application import public as workflows
    from app.orchestration.runner import open_runner

    async with open_runner(settings.database_url) as runner:
        workflows.install_runner(runner)
        try:
            yield
        finally:
            workflows.install_runner(None)


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
    gateway: ModelGatewayPort | None = None,
    alive_interval_s: float = ALIVE_INTERVAL_S,
    graph_runner: bool = True,
) -> None:
    """Claim and run jobs until `stop` is set.

    `job_types` limits what this worker claims (default: every registered type). An engine
    or gateway passed in is left open; one created here is closed on exit. The gateway is
    installed for handlers while this runs, and so is the graph runner unless
    `graph_runner` is False (tests that install their own)."""
    settings = settings or get_settings()
    poll = poll_s if poll_s is not None else settings.worker_poll_s
    types = frozenset(REGISTRY) if job_types is None else frozenset(job_types)
    lease = LeaseSettings(lease_s=settings.job_lease_s, heartbeat_s=settings.job_heartbeat_s)
    owner = worker_id()
    own_engine = engine is None
    db = engine if engine is not None else create_engine(settings)
    own_gateway = gateway is None
    models: ModelGatewayPort | None = gateway
    alive = (
        asyncio.create_task(_keep_alive(settings.worker_alive_file, stop, alive_interval_s))
        if settings.worker_alive_file is not None
        else None
    )
    stack = contextlib.AsyncExitStack()
    try:
        if models is None:
            models = ModelGateway(settings, db)
        model_gateway.install(models)
        # Only a worker that claims `workflows.execute` or `workflows.resume` jobs needs the
        # graph runner.
        await stack.enter_async_context(
            _graph_runner(settings, graph_runner and bool(GRAPH_JOB_TYPES & types))
        )
        _log.info(
            "worker.started",
            extra={
                "version": settings.version,
                "env": settings.env,
                "worker_id": owner,
                "job_types": sorted(types),
            },
        )
        schedules_due_at = 0.0
        while not stop.is_set():
            if time.monotonic() >= schedules_due_at:
                await _enqueue_schedules(db, types)
                schedules_due_at = time.monotonic() + SCHEDULE_CHECK_S
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
        await stack.aclose()
        if alive is not None:
            alive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await alive
        model_gateway.install(None)
        if own_gateway and isinstance(models, ModelGateway):
            await models.aclose()
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
