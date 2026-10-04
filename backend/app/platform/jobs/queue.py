"""Queue operations on `platform_jobs` (AD-29): enqueue, claim, heartbeat, complete, fail.

`enqueue` joins the caller's Unit of Work, so a rolled-back command enqueues nothing. The
other operations each run in their own short transaction (`unit_of_work`), and none is held
open while a handler runs (AD-25).

A claim is identified by `(job id, lease_owner, attempts)`. Heartbeats and finishes only
touch the row while that claim still holds it, so a job reclaimed after its lease expired
ignores the stale holder's late heartbeat, completion or failure.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.ids import new_id
from app.platform.jobs.models import PlatformJob
from app.platform.jobs.registry import JobPayload, for_payload
from app.platform.uow import UnitOfWork, unit_of_work

_t = PlatformJob
MAX_ERROR_CHARS = 300


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: UUID
    job_type: str
    payload: dict[str, Any]
    attempts: int
    opportunity_id: UUID | None
    lease_owner: str


async def enqueue(
    uow: UnitOfWork,
    payload: JobPayload,
    *,
    opportunity_id: UUID | None = None,
    run_after: datetime | None = None,
) -> UUID:
    """Insert a `queued` job inside the caller's Unit of Work and return its UUIDv7 id.

    Raises `UnknownJobTypeError` if the payload's class is not registered, and a Pydantic
    `ValidationError` if the payload does not validate against its model."""
    spec = for_payload(payload)
    data = payload.model_dump(mode="json")
    spec.payload.model_validate(data)  # the stored form must load back in the worker
    job_id = new_id()
    await uow.session.execute(
        insert(PlatformJob).values(
            id=job_id,
            job_type=spec.name,
            payload=data,
            priority=spec.rank,
            status="queued",
            attempts=0,
            run_after=run_after if run_after is not None else func.now(),
            opportunity_id=opportunity_id,
        )
    )
    return job_id


async def claim(
    engine: AsyncEngine, *, owner: str, lease_s: float, job_types: Collection[str]
) -> ClaimedJob | None:
    """Claim the next eligible job of one of `job_types`, or return None.

    Eligible: `queued` or `failed_retrying` with `run_after <= now()`, or `running` with an
    expired lease. Ordered by priority, then `run_after`, then `created_at`; locked rows are
    skipped, so concurrent claimers never get the same job. The claim sets `running`, the
    lease and increments `attempts`, all in one short transaction."""
    if not job_types:
        return None
    eligible = or_(
        and_(_t.status.in_(("queued", "failed_retrying")), _t.run_after <= func.now()),
        and_(_t.status == "running", _t.lease_expires_at < func.now()),
    )
    next_id = (
        select(_t.id)
        .where(_t.job_type.in_(list(job_types)), eligible)
        .order_by(_t.priority, _t.run_after, _t.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        update(_t)
        .where(_t.id == next_id)
        .values(
            status="running",
            lease_owner=owner,
            lease_expires_at=func.now() + timedelta(seconds=lease_s),
            attempts=_t.attempts + 1,
            updated_at=func.now(),
        )
        .returning(_t.id, _t.job_type, _t.payload, _t.attempts, _t.opportunity_id)
    )
    async with unit_of_work(engine) as uow:
        row = (await uow.session.execute(statement)).one_or_none()
    if row is None:
        return None
    return ClaimedJob(
        id=row.id,
        job_type=row.job_type,
        payload=row.payload,
        attempts=row.attempts,
        opportunity_id=row.opportunity_id,
        lease_owner=owner,
    )


def _held(job: ClaimedJob) -> Any:
    return and_(
        _t.id == job.id,
        _t.status == "running",
        _t.lease_owner == job.lease_owner,
        _t.attempts == job.attempts,
    )


async def _update_held(engine: AsyncEngine, job: ClaimedJob, values: dict[str, Any]) -> bool:
    statement = update(_t).where(_held(job)).values(updated_at=func.now(), **values)
    async with unit_of_work(engine) as uow:
        result = await uow.session.execute(statement.returning(_t.id))
        return result.one_or_none() is not None


async def heartbeat(engine: AsyncEngine, job: ClaimedJob, *, lease_s: float) -> bool:
    """Extend the lease. False if the claim no longer holds the job."""
    return await _update_held(
        engine, job, {"lease_expires_at": func.now() + timedelta(seconds=lease_s)}
    )


async def complete(engine: AsyncEngine, job: ClaimedJob) -> bool:
    """Mark the job `succeeded` and clear its lease. False (and no change) if the claim no
    longer holds the job."""
    return await _update_held(
        engine,
        job,
        {"status": "succeeded", "lease_owner": None, "lease_expires_at": None, "last_error": None},
    )


async def fail(
    engine: AsyncEngine, job: ClaimedJob, *, error: str, retry_in_s: float | None
) -> Literal["failed_retrying", "dead"] | None:
    """Record a failure: `failed_retrying` with `run_after = now() + retry_in_s`, or `dead`
    when `retry_in_s` is None. Returns the new status, or None (and no change) if the claim
    no longer holds the job. `error` must be a short technical reason, no customer content."""
    status: Literal["failed_retrying", "dead"] = "dead" if retry_in_s is None else "failed_retrying"
    values: dict[str, Any] = {
        "status": status,
        "lease_owner": None,
        "lease_expires_at": None,
        "last_error": error[:MAX_ERROR_CHARS],
    }
    if retry_in_s is not None:
        values["run_after"] = func.now() + timedelta(seconds=retry_in_s)
    return status if await _update_held(engine, job, values) else None


async def release(engine: AsyncEngine, job: ClaimedJob) -> bool:
    """Give an abandoned claim back to the queue without counting the attempt (the worker
    stopped before the handler finished). False if the claim no longer holds the job."""
    return await _update_held(
        engine,
        job,
        {
            "status": "queued",
            "lease_owner": None,
            "lease_expires_at": None,
            "attempts": _t.attempts - 1,
            "run_after": func.now(),
        },
    )
