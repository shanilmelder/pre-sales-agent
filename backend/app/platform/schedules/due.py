"""Enqueue the jobs of due schedules (AD-29; Story 5.2).

Each due row (`next_run_at <= now()`) is locked with `FOR UPDATE SKIP LOCKED`, its job
enqueued (the job type's payload takes no fields) and `next_run_at` moved one interval on
from now, all in one short transaction, so concurrent workers never enqueue a schedule
twice. A schedule whose job type this process has not registered is left for a worker that
has.
"""

from collections.abc import Collection
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.jobs.queue import enqueue
from app.platform.jobs.registry import REGISTRY
from app.platform.logging import get_logger
from app.platform.schedules.models import PlatformSchedule
from app.platform.uow import unit_of_work

_log = get_logger(__name__)


async def enqueue_due(engine: AsyncEngine, job_types: Collection[str] | None = None) -> list[str]:
    """Enqueue one job per due schedule (only of `job_types`, when given: the types this
    worker claims); returns the schedules enqueued."""
    enqueued: list[str] = []
    if job_types is not None and not any(t in REGISTRY for t in job_types):
        return enqueued
    async with unit_of_work(engine) as uow:
        rows = (
            await uow.session.execute(
                select(PlatformSchedule)
                .where(PlatformSchedule.next_run_at <= func.now())
                .order_by(PlatformSchedule.name)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        for row in list(rows):
            spec = REGISTRY.get(row.job_type)
            if spec is None or (job_types is not None and row.job_type not in job_types):
                continue
            await enqueue(uow, spec.payload())
            await uow.session.execute(
                update(PlatformSchedule)
                .where(PlatformSchedule.name == row.name)
                .values(
                    next_run_at=func.now() + timedelta(seconds=row.interval_s),
                    last_enqueued_at=func.now(),
                )
                .execution_options(synchronize_session=False)
            )
            enqueued.append(row.name)
    for name in enqueued:
        _log.info("schedules.enqueued", extra={"schedule": name})
    return enqueued
