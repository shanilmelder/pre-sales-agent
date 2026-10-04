"""Run one claimed job (AD-29): payload validation, timeout, heartbeat, finish.

Only the `worker` process imports this module; the `api` process never does (import-linter
contract in pyproject.toml and tests/test_architecture.py).

The runner holds no transaction while the handler runs: the claim, each heartbeat and the
finish are separate short Units of Work, and the handler opens its own (AD-25).
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.jobs import queue
from app.platform.jobs.queue import ClaimedJob
from app.platform.jobs.registry import JobContext, UnknownJobTypeError, get
from app.platform.logging import get_logger

_log = get_logger("app.jobs")
_ERROR_MESSAGE_CHARS = 200

Outcome = Literal["succeeded", "failed_retrying", "dead", "lease_lost"]


@dataclass(frozen=True, slots=True)
class LeaseSettings:
    lease_s: float = 30.0
    heartbeat_s: float = 10.0


def short_error(exc: BaseException) -> str:
    """`ExceptionClass: first line of the message`, truncated. Stored in `last_error`, never
    logged. Handlers raise technical messages only, never customer content."""
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    message = message[:_ERROR_MESSAGE_CHARS]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


async def _keep_lease(
    engine: AsyncEngine, job: ClaimedJob, lease: LeaseSettings, work: asyncio.Task[None]
) -> None:
    """Extend the lease every `heartbeat_s` until cancelled. If the lease is lost (the job
    was reclaimed), cancel the handler: its result would be discarded anyway."""
    while True:
        await asyncio.sleep(lease.heartbeat_s)
        try:
            held = await queue.heartbeat(engine, job, lease_s=lease.lease_s)
        except Exception as exc:  # a transient DB error must not kill the job
            _log.warning(
                "jobs.heartbeat_failed",
                extra={"job_id": str(job.id), "exc_type": type(exc).__name__},
            )
            continue
        if not held:
            _log.warning("jobs.lease_lost", extra={"job_id": str(job.id), "job_type": job.job_type})
            work.cancel()
            return


async def _shielded[T](finish: Awaitable[T]) -> T:
    """Run a finish write to the end even if this task is cancelled meanwhile (a worker
    stop): once the handler has returned, its result must land, or a completed job would
    run again. On cancellation, wait for the write, then re-raise."""
    write = asyncio.ensure_future(finish)
    try:
        return await asyncio.shield(write)
    except asyncio.CancelledError:
        await asyncio.wait({write})
        raise


async def _finish_failed(
    engine: AsyncEngine, job: ClaimedJob, *, error: str, retry_in_s: float | None, exc_type: str
) -> Outcome:
    status = await queue.fail(engine, job, error=error, retry_in_s=retry_in_s)
    ids = {"job_id": str(job.id), "job_type": job.job_type, "attempts": job.attempts}
    if status is None:
        _log.warning("jobs.lease_lost", extra=ids)
        return "lease_lost"
    if status == "dead":
        _log.error("jobs.dead", extra={**ids, "exc_type": exc_type})
    else:
        _log.warning("jobs.failed", extra={**ids, "exc_type": exc_type, "retry_in_s": retry_in_s})
    return status


async def run_job(engine: AsyncEngine, job: ClaimedJob, lease: LeaseSettings) -> Outcome:
    """Run a claimed job's handler under its timeout with a heartbeat, then record the result.

    An exception or timeout becomes `failed_retrying` (with the job type's backoff) or, once
    attempts are exhausted, `dead`. If this task is cancelled (the worker is stopping) while
    the handler runs, the handler is cancelled and the claim released back to the queue, then
    CancelledError is re-raised. Once the handler has returned or failed, the finish write is
    shielded: a cancellation waits for it to land, then re-raises."""
    ids = {"job_id": str(job.id), "job_type": job.job_type, "attempts": job.attempts}
    try:
        spec = get(job.job_type)
    except UnknownJobTypeError as exc:
        return await _finish_failed(
            engine, job, error=short_error(exc), retry_in_s=None, exc_type=type(exc).__name__
        )
    if job.attempts > spec.max_attempts:
        # Reclaimed after its final attempt lost its lease (e.g. the worker was killed).
        return await _finish_failed(
            engine,
            job,
            error="AttemptsExhausted: lease expired on the final attempt",
            retry_in_s=None,
            exc_type="AttemptsExhausted",
        )
    try:
        payload = spec.payload.model_validate(job.payload)
    except ValidationError as exc:
        # Retrying cannot fix a payload; Pydantic messages may echo values, so class only.
        return await _finish_failed(
            engine, job, error="ValidationError", retry_in_s=None, exc_type=type(exc).__name__
        )

    ctx = JobContext(
        job_id=job.id,
        job_type=job.job_type,
        attempt=job.attempts,
        max_attempts=spec.max_attempts,
        opportunity_id=job.opportunity_id,
        engine=engine,
    )

    async def _handle() -> None:
        async with asyncio.timeout(spec.timeout_s):
            await spec.handler(ctx, payload)

    _log.info("jobs.started", extra=ids)
    started = time.monotonic()
    work = asyncio.create_task(_handle())
    keeper = asyncio.create_task(_keep_lease(engine, job, lease, work))
    error: BaseException | None = None
    try:
        await work
    except asyncio.CancelledError as exc:
        if _cancelling():
            # This task is being cancelled: the worker is abandoning the job.
            work.cancel()
            with contextlib.suppress(BaseException):
                await work
            keeper.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(_release(engine, job))
            raise
        if keeper.done() and not keeper.cancelled():
            # The heartbeat found the lease lost and cancelled the handler.
            return "lease_lost"
        error = exc  # the handler raised CancelledError itself: an ordinary failure
    except Exception as exc:  # TimeoutError included
        error = exc
    finally:
        keeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keeper

    duration_ms = round((time.monotonic() - started) * 1000)
    if error is None:
        if await _shielded(queue.complete(engine, job)):
            _log.info("jobs.succeeded", extra={**ids, "duration_ms": duration_ms})
            return "succeeded"
        _log.warning("jobs.lease_lost", extra={**ids, "duration_ms": duration_ms})
        return "lease_lost"

    if isinstance(error, TimeoutError):
        message = f"TimeoutError: exceeded {spec.timeout_s:g}s"
    else:
        message = short_error(error)
    retry_in_s = None if job.attempts >= spec.max_attempts else spec.backoff_s(job.attempts)
    return await _shielded(
        _finish_failed(
            engine, job, error=message, retry_in_s=retry_in_s, exc_type=type(error).__name__
        )
    )


def _cancelling() -> int:
    task = asyncio.current_task()
    return task.cancelling() if task is not None else 0


async def _release(engine: AsyncEngine, job: ClaimedJob) -> None:
    try:
        released = await queue.release(engine, job)
    except Exception as exc:
        _log.warning(
            "jobs.release_failed", extra={"job_id": str(job.id), "exc_type": type(exc).__name__}
        )
        return
    _log.info("jobs.released", extra={"job_id": str(job.id), "released": released})
