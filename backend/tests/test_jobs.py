"""The Postgres job queue (AD-29, Story 2.2 Part A): enqueue, claim, lease, retry, dead.

Integration tests against Postgres as `psa_app`. Test-only job types (`testjobs.*`) are
registered here; every claim is limited to them, so other rows in the database are never
touched. `psa_app` cannot delete jobs, so the fixture retires leftover test rows instead.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

import app.main_worker as main_worker
from app.main_worker import run as run_worker
from app.platform import jobs
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, UnknownJobTypeError, register
from app.platform.jobs import queue as q
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.uow import unit_of_work
from tests.conftest import run_async

CALLS: Counter[str] = Counter()


class OkPayload(JobPayload):
    marker: str


class UrgentPayload(JobPayload):
    marker: str


class FlakyPayload(JobPayload):
    marker: str


class FatalPayload(JobPayload):
    marker: str


class SlowPayload(JobPayload):
    marker: str
    sleep_s: float


class LongPayload(JobPayload):
    marker: str
    sleep_s: float


class SelfCancelPayload(JobPayload):
    marker: str


class NeverRegistered(JobPayload):
    marker: str


async def _count(ctx: JobContext, payload: OkPayload | UrgentPayload) -> None:
    CALLS[payload.marker] += 1


async def _raise(ctx: JobContext, payload: FlakyPayload | FatalPayload) -> None:
    CALLS[payload.marker] += 1
    raise RuntimeError("handler failed on purpose")


async def _sleep(ctx: JobContext, payload: SlowPayload | LongPayload) -> None:
    await asyncio.sleep(payload.sleep_s)
    CALLS[payload.marker] += 1


register(JobType(name="testjobs.ok", payload=OkPayload, handler=_count))
register(
    JobType(name="testjobs.urgent", payload=UrgentPayload, handler=_count, priority="interactive")
)
register(
    JobType(
        name="testjobs.flaky",
        payload=FlakyPayload,
        handler=_raise,
        max_attempts=3,
        backoff_base_s=60,
        backoff_cap_s=600,
    )
)
register(JobType(name="testjobs.fatal", payload=FatalPayload, handler=_raise, max_attempts=1))
register(
    JobType(
        name="testjobs.slow", payload=SlowPayload, handler=_sleep, timeout_s=0.3, max_attempts=2
    )
)
register(JobType(name="testjobs.long", payload=LongPayload, handler=_sleep, timeout_s=5))


async def _cancel_self(ctx: JobContext, payload: SelfCancelPayload) -> None:
    CALLS[payload.marker] += 1
    raise asyncio.CancelledError  # e.g. a library cancelling its own task


register(JobType(name="testjobs.self_cancel", payload=SelfCancelPayload, handler=_cancel_self))
TEST_TYPES = tuple(name for name in jobs.REGISTRY if name.startswith("testjobs."))
LEASE = LeaseSettings(lease_s=5, heartbeat_s=1)


@pytest.fixture
def jobs_db(db_url: str, sync_engine: Engine) -> Iterator[str]:
    """Retire unfinished test jobs left by earlier runs so claims see only this test's."""
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead', lease_owner = NULL, "
                "lease_expires_at = NULL WHERE job_type LIKE 'testjobs.%' "
                "AND status IN ('queued', 'running', 'failed_retrying')"
            )
        )
    yield db_url


def _with_engine[T](db_url: str, scenario: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def wrapped() -> T:
        engine = create_engine(Settings(database_url=db_url))
        try:
            return await scenario(engine)
        finally:
            await engine.dispose()

    return run_async(wrapped())


def _row(engine: Engine, job_id: UUID) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT *, now() AS db_now FROM platform_jobs WHERE id = :id"), {"id": job_id}
        ).one()
    return dict(row._mapping)


def _count_marker(engine: Engine, marker: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM platform_jobs WHERE payload->>'marker' = :m"),
            {"m": marker},
        ).scalar_one()


async def _enqueue(engine: AsyncEngine, payload: JobPayload, **kwargs: Any) -> UUID:
    async with unit_of_work(engine) as uow:
        return await jobs.enqueue(uow, payload, **kwargs)


async def _claim(engine: AsyncEngine, owner: str = "w1", lease_s: float = 5) -> q.ClaimedJob | None:
    return await q.claim(engine, owner=owner, lease_s=lease_s, job_types=TEST_TYPES)


async def _expire_lease(engine: AsyncEngine, job_id: UUID) -> None:
    async with unit_of_work(engine) as uow:
        await uow.session.execute(
            sa.text(
                "UPDATE platform_jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :id"
            ),
            {"id": job_id},
        )


async def _status(engine: AsyncEngine, job_id: UUID) -> str:
    async with unit_of_work(engine) as uow:
        result = await uow.session.execute(
            sa.text("SELECT status FROM platform_jobs WHERE id = :id"), {"id": job_id}
        )
        status: str = result.scalar_one()
        return status


def _insert_raw(engine: Engine, job_type: str, payload: str) -> UUID:
    job_id = new_id()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_jobs (id, job_type, payload, priority, status, attempts, "
                "run_after) VALUES (:id, :t, CAST(:p AS jsonb), 1, 'queued', 0, now())"
            ),
            {"id": job_id, "t": job_type, "p": payload},
        )
    return job_id


def _marker(request: pytest.FixtureRequest) -> str:
    return f"{request.node.name}-{datetime.now(UTC).timestamp()}"


# --- registry -----------------------------------------------------------------------------


def test_registry_rejects_bad_names_and_duplicates() -> None:
    class Other(JobPayload):
        x: int

    with pytest.raises(ValueError, match=r"<module>\.<verb>"):
        JobType(name="NoDot", payload=Other, handler=_count)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already registered"):
        register(JobType(name="testjobs.ok", payload=Other, handler=_count))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already the payload"):
        register(JobType(name="testjobs.other", payload=OkPayload, handler=_count))


def test_backoff_is_exponential_and_capped() -> None:
    spec = jobs.REGISTRY["testjobs.flaky"]
    assert [spec.backoff_s(n) for n in (1, 2, 3, 4, 5, 100)] == [60, 120, 240, 480, 600, 600]


# --- enqueue ------------------------------------------------------------------------------


def test_enqueue_commits_one_queued_row(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)
    opportunity_id = UUID(int=42)

    async def scenario(engine: AsyncEngine) -> UUID:
        return await _enqueue(engine, OkPayload(marker=marker), opportunity_id=opportunity_id)

    job_id = _with_engine(jobs_db, scenario)
    row = _row(sync_engine, job_id)
    assert row["job_type"] == "testjobs.ok"
    assert row["status"] == "queued"
    assert row["attempts"] == 0
    assert row["priority"] == 1
    assert row["payload"] == {"marker": marker}
    assert row["opportunity_id"] == opportunity_id
    assert row["run_after"] <= row["db_now"]
    assert job_id.version == 7
    assert _count_marker(sync_engine, marker) == 1


def test_enqueue_in_a_rolled_back_unit_of_work_inserts_nothing(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> None:
        with pytest.raises(RuntimeError):
            async with unit_of_work(engine) as uow:
                await jobs.enqueue(uow, OkPayload(marker=marker))
                await uow.flush()
                raise RuntimeError("command failed")

    _with_engine(jobs_db, scenario)
    assert _count_marker(sync_engine, marker) == 0


def test_enqueue_unknown_type_raises_and_inserts_nothing(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> None:
        async with unit_of_work(engine) as uow:  # commits: only the enqueue fails
            with pytest.raises(UnknownJobTypeError):
                await jobs.enqueue(uow, NeverRegistered(marker=marker))

    _with_engine(jobs_db, scenario)
    assert _count_marker(sync_engine, marker) == 0


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_enqueue_validates_the_payload(jobs_db: str, request: pytest.FixtureRequest) -> None:
    bogus = SlowPayload.model_construct(marker=_marker(request), sleep_s="not a number")

    async def scenario(engine: AsyncEngine) -> None:
        async with unit_of_work(engine) as uow:
            with pytest.raises(ValidationError):
                await jobs.enqueue(uow, bogus)

    _with_engine(jobs_db, scenario)


def test_app_role_cannot_delete_jobs(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            conn.execute(sa.text("DELETE FROM platform_jobs WHERE false"))
        conn.rollback()


# --- claim --------------------------------------------------------------------------------


def test_interactive_is_claimed_before_background(
    jobs_db: str, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> list[str | None]:
        await _enqueue(engine, OkPayload(marker=marker))
        await _enqueue(engine, UrgentPayload(marker=marker))
        first, second, third = await _claim(engine), await _claim(engine), await _claim(engine)
        return [j.job_type if j else None for j in (first, second, third)]

    assert _with_engine(jobs_db, scenario) == ["testjobs.urgent", "testjobs.ok", None]


def test_two_workers_one_job_exactly_one_claims(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, list[q.ClaimedJob | None]]:
        job_id = await _enqueue(engine, OkPayload(marker=marker))
        claims = await asyncio.gather(*(_claim(engine, owner=f"w{i}") for i in range(4)))
        return job_id, list(claims)

    job_id, claims = _with_engine(jobs_db, scenario)
    won = [c for c in claims if c is not None]
    assert len(won) == 1
    assert won[0].id == job_id and won[0].attempts == 1
    row = _row(sync_engine, job_id)
    assert row["status"] == "running"
    assert row["lease_owner"] == won[0].lease_owner
    assert row["lease_expires_at"] > row["db_now"]


def test_same_priority_earlier_run_after_is_claimed_first(
    jobs_db: str, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, list[UUID | None]]:
        now = datetime.now(UTC)
        await _enqueue(engine, OkPayload(marker=marker), run_after=now - timedelta(seconds=10))
        earlier = await _enqueue(
            engine, OkPayload(marker=marker), run_after=now - timedelta(seconds=60)
        )
        first, second = await _claim(engine), await _claim(engine)
        return earlier, [j.id if j else None for j in (first, second)]

    earlier, claimed = _with_engine(jobs_db, scenario)
    assert claimed[0] == earlier
    assert claimed[1] is not None and claimed[1] != earlier


def test_job_with_future_run_after_is_not_claimed(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, q.ClaimedJob | None]:
        later = datetime.now(UTC) + timedelta(hours=1)
        job_id = await _enqueue(engine, OkPayload(marker=marker), run_after=later)
        return job_id, await _claim(engine)

    job_id, claimed = _with_engine(jobs_db, scenario)
    assert claimed is None
    assert _row(sync_engine, job_id)["status"] == "queued"


def test_claim_without_job_types_claims_nothing(jobs_db: str) -> None:
    async def scenario(engine: AsyncEngine) -> q.ClaimedJob | None:
        return await q.claim(engine, owner="w1", lease_s=5, job_types=())

    assert _with_engine(jobs_db, scenario) is None


# --- running ------------------------------------------------------------------------------


def test_success_marks_succeeded_and_clears_the_lease(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str]:
        job_id = await _enqueue(engine, OkPayload(marker=marker))
        claimed = await _claim(engine)
        assert claimed is not None
        return job_id, await run_job(engine, claimed, LEASE)

    job_id, outcome = _with_engine(jobs_db, scenario)
    assert outcome == "succeeded"
    row = _row(sync_engine, job_id)
    assert (row["status"], row["lease_owner"], row["lease_expires_at"]) == ("succeeded", None, None)
    assert row["attempts"] == 1
    assert CALLS[marker] == 1


def test_failure_retries_with_backoff(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str]:
        job_id = await _enqueue(engine, FlakyPayload(marker=marker))
        claimed = await _claim(engine)
        assert claimed is not None
        return job_id, await run_job(engine, claimed, LEASE)

    job_id, outcome = _with_engine(jobs_db, scenario)
    assert outcome == "failed_retrying"
    row = _row(sync_engine, job_id)
    assert row["status"] == "failed_retrying"
    assert row["attempts"] == 1
    assert row["last_error"] == "RuntimeError: handler failed on purpose"
    assert row["lease_owner"] is None
    delay = (row["run_after"] - row["db_now"]).total_seconds()
    assert 55 < delay <= 60  # attempt 1: the base backoff


def test_timeout_is_a_failure(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str]:
        job_id = await _enqueue(engine, SlowPayload(marker=marker, sleep_s=5))
        claimed = await _claim(engine)
        assert claimed is not None
        return job_id, await run_job(engine, claimed, LEASE)

    job_id, outcome = _with_engine(jobs_db, scenario)
    assert outcome == "failed_retrying"
    row = _row(sync_engine, job_id)
    assert row["status"] == "failed_retrying"
    assert row["last_error"] == "TimeoutError: exceeded 0.3s"
    assert CALLS[marker] == 0  # the handler was cancelled


def test_final_failure_is_dead_and_logged(
    jobs_db: str,
    sync_engine: Engine,
    request: pytest.FixtureRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str]:
        job_id = await _enqueue(engine, FatalPayload(marker=marker))
        claimed = await _claim(engine)
        assert claimed is not None
        return job_id, await run_job(engine, claimed, LEASE)

    with caplog.at_level(logging.INFO, logger="app.jobs"):
        job_id, outcome = _with_engine(jobs_db, scenario)
    assert outcome == "dead"
    row = _row(sync_engine, job_id)
    assert (row["status"], row["attempts"], row["lease_owner"]) == ("dead", 1, None)
    assert row["last_error"] == "RuntimeError: handler failed on purpose"
    dead = [r for r in caplog.records if r.getMessage() == "jobs.dead"]
    assert len(dead) == 1
    assert dead[0].levelno == logging.ERROR
    assert dead[0].__dict__["job_id"] == str(job_id)
    assert dead[0].__dict__["job_type"] == "testjobs.fatal"


def test_flaky_job_is_dead_after_max_attempts(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, list[str]]:
        job_id = await _enqueue(engine, FlakyPayload(marker=marker))
        outcomes = []
        for _ in range(3):
            claimed = await _claim(engine)
            assert claimed is not None
            outcomes.append(await run_job(engine, claimed, LEASE))
            async with unit_of_work(engine) as uow:  # skip the backoff wait
                await uow.session.execute(
                    sa.text("UPDATE platform_jobs SET run_after = now() WHERE id = :id"),
                    {"id": job_id},
                )
        return job_id, outcomes

    job_id, outcomes = _with_engine(jobs_db, scenario)
    assert outcomes == ["failed_retrying", "failed_retrying", "dead"]
    assert _row(sync_engine, job_id)["attempts"] == 3
    assert CALLS[marker] == 3


# --- leases -------------------------------------------------------------------------------


def test_killed_worker_job_is_reclaimed_and_succeeds_once(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> UUID:
        job_id = await _enqueue(engine, OkPayload(marker=marker))
        stale = await _claim(engine, owner="killed-worker")  # then "dies"
        assert stale is not None and stale.id == job_id
        assert await _claim(engine, owner="live-worker") is None  # lease still valid
        await _expire_lease(engine, job_id)
        fresh = await _claim(engine, owner="live-worker")
        assert fresh is not None and fresh.id == job_id and fresh.attempts == 2
        assert await run_job(engine, fresh, LEASE) == "succeeded"
        # The stale holder's late heartbeat, completion or failure changes nothing.
        assert await q.heartbeat(engine, stale, lease_s=5) is False
        assert await q.complete(engine, stale) is False
        assert await q.fail(engine, stale, error="late", retry_in_s=1) is None
        return job_id

    job_id = _with_engine(jobs_db, scenario)
    row = _row(sync_engine, job_id)
    assert (row["status"], row["attempts"], row["last_error"]) == ("succeeded", 2, None)
    assert CALLS[marker] == 1


def test_reclaimed_after_final_attempt_is_dead_without_running(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str]:
        job_id = await _enqueue(engine, FatalPayload(marker=marker))
        assert await _claim(engine, owner="killed-worker") is not None
        await _expire_lease(engine, job_id)
        fresh = await _claim(engine, owner="live-worker")
        assert fresh is not None and fresh.attempts == 2
        return job_id, await run_job(engine, fresh, LEASE)

    job_id, outcome = _with_engine(jobs_db, scenario)
    assert outcome == "dead"
    assert _row(sync_engine, job_id)["last_error"].startswith("AttemptsExhausted")
    assert CALLS[marker] == 0


def test_heartbeat_keeps_a_long_job_from_being_reclaimed(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)
    lease = LeaseSettings(lease_s=0.3, heartbeat_s=0.1)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str, list[q.ClaimedJob | None]]:
        job_id = await _enqueue(engine, LongPayload(marker=marker, sleep_s=0.9))
        claimed = await _claim(engine, lease_s=lease.lease_s)
        assert claimed is not None
        task = asyncio.create_task(run_job(engine, claimed, lease))
        rivals = []
        for _ in range(3):  # well past the original lease
            await asyncio.sleep(0.2)
            rivals.append(await _claim(engine, owner="rival"))
        return job_id, await task, rivals

    job_id, outcome, rivals = _with_engine(jobs_db, scenario)
    assert rivals == [None, None, None]
    assert outcome == "succeeded"
    assert _row(sync_engine, job_id)["attempts"] == 1
    assert CALLS[marker] == 1


def test_lost_lease_discards_the_late_result(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)
    no_beat = LeaseSettings(lease_s=5, heartbeat_s=60)  # simulates a stalled holder

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str, q.ClaimedJob | None]:
        job_id = await _enqueue(engine, LongPayload(marker=marker, sleep_s=0.4))
        claimed = await _claim(engine, owner="slow", lease_s=no_beat.lease_s)
        assert claimed is not None
        task = asyncio.create_task(run_job(engine, claimed, no_beat))
        await asyncio.sleep(0.05)
        await _expire_lease(engine, job_id)
        rival = await _claim(engine, owner="rival")
        return job_id, await task, rival

    job_id, outcome, rival = _with_engine(jobs_db, scenario)
    assert rival is not None and rival.id == job_id
    assert outcome == "lease_lost"
    row = _row(sync_engine, job_id)
    assert (row["status"], row["lease_owner"], row["attempts"]) == ("running", "rival", 2)


def test_heartbeat_detects_a_lost_lease_and_cancels_the_handler(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)
    lease = LeaseSettings(lease_s=0.6, heartbeat_s=0.2)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str, float]:
        job_id = await _enqueue(engine, LongPayload(marker=marker, sleep_s=2))
        claimed = await _claim(engine, owner="holder", lease_s=lease.lease_s)
        assert claimed is not None
        started = asyncio.get_running_loop().time()
        task = asyncio.create_task(run_job(engine, claimed, lease))
        await asyncio.sleep(0.05)
        await _expire_lease(engine, job_id)
        assert await _claim(engine, owner="rival") is not None
        outcome = await task
        return job_id, outcome, asyncio.get_running_loop().time() - started

    job_id, outcome, elapsed = _with_engine(jobs_db, scenario)
    assert outcome == "lease_lost"
    assert elapsed < 1.5  # cancelled at the next beat, not left to finish
    assert CALLS[marker] == 0
    row = _row(sync_engine, job_id)
    assert (row["status"], row["lease_owner"], row["attempts"]) == ("running", "rival", 2)


def test_a_failing_heartbeat_does_not_kill_the_job(
    jobs_db: str,
    sync_engine: Engine,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker(request)
    real_heartbeat = q.heartbeat
    failures: list[int] = []

    async def flaky_heartbeat(engine: AsyncEngine, job: q.ClaimedJob, *, lease_s: float) -> bool:
        if not failures:
            failures.append(1)
            raise OSError("connection reset")
        return await real_heartbeat(engine, job, lease_s=lease_s)

    monkeypatch.setattr(q, "heartbeat", flaky_heartbeat)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, str]:
        job_id = await _enqueue(engine, LongPayload(marker=marker, sleep_s=0.35))
        claimed = await _claim(engine, lease_s=2)
        assert claimed is not None
        return job_id, await run_job(engine, claimed, LeaseSettings(lease_s=2, heartbeat_s=0.1))

    job_id, outcome = _with_engine(jobs_db, scenario)
    assert failures == [1]
    assert outcome == "succeeded"
    assert _row(sync_engine, job_id)["status"] == "succeeded"
    assert CALLS[marker] == 1


def test_invalid_stored_payload_is_dead(jobs_db: str, sync_engine: Engine) -> None:
    job_id = _insert_raw(sync_engine, "testjobs.ok", '{"wrong": 1}')

    async def scenario(engine: AsyncEngine) -> str:
        claimed = await _claim(engine)
        assert claimed is not None and claimed.id == job_id
        return await run_job(engine, claimed, LEASE)

    assert _with_engine(jobs_db, scenario) == "dead"
    row = _row(sync_engine, job_id)
    assert (row["status"], row["last_error"], row["attempts"]) == ("dead", "ValidationError", 1)


def test_unregistered_job_type_is_dead(jobs_db: str, sync_engine: Engine) -> None:
    job_id = _insert_raw(sync_engine, "testjobs.unregistered", "{}")

    async def scenario(engine: AsyncEngine) -> str:
        claimed = await q.claim(engine, owner="w1", lease_s=5, job_types=("testjobs.unregistered",))
        assert claimed is not None and claimed.id == job_id
        return await run_job(engine, claimed, LEASE)

    assert _with_engine(jobs_db, scenario) == "dead"
    row = _row(sync_engine, job_id)
    assert row["status"] == "dead"
    assert row["last_error"].startswith("UnknownJobTypeError")


def test_cancelled_run_releases_the_job(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> UUID:
        job_id = await _enqueue(engine, LongPayload(marker=marker, sleep_s=0.4))
        claimed = await _claim(engine)
        assert claimed is not None
        task = asyncio.create_task(run_job(engine, claimed, LEASE))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return job_id

    job_id = _with_engine(jobs_db, scenario)
    row = _row(sync_engine, job_id)
    assert (row["status"], row["attempts"], row["lease_owner"]) == ("queued", 0, None)
    assert CALLS[marker] == 0


# --- the worker loop ----------------------------------------------------------------------


def test_worker_claims_and_runs_queued_jobs(
    jobs_db: str,
    sync_engine: Engine,
    request: pytest.FixtureRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> list[UUID]:
        ids = [await _enqueue(engine, OkPayload(marker=marker)) for _ in range(2)]
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(
                stop,
                settings=Settings(database_url=jobs_db),
                engine=engine,
                poll_s=0.05,
                job_types=TEST_TYPES,
            )
        )

        async def both_succeeded() -> bool:
            return [await _status(engine, i) for i in ids] == ["succeeded", "succeeded"]

        await _wait_for(both_succeeded)
        stop.set()
        await asyncio.wait_for(worker, timeout=2)
        return ids

    with caplog.at_level(logging.INFO):
        ids = _with_engine(jobs_db, scenario)
    app_records = [r for r in caplog.records if r.name.startswith("app.")]
    assert [_row(sync_engine, i)["status"] for i in ids] == ["succeeded", "succeeded"]
    assert CALLS[marker] == 2
    events = [r.getMessage() for r in app_records]
    assert events.count("jobs.succeeded") == 2
    assert events[0] == "worker.started" and events[-1] == "worker.stopped"


def _start_worker(engine: AsyncEngine, db_url: str, stop: asyncio.Event) -> asyncio.Task[None]:
    return asyncio.create_task(
        run_worker(
            stop,
            settings=Settings(database_url=db_url),
            engine=engine,
            poll_s=0.05,
            job_types=TEST_TYPES,
        )
    )


async def _wait_for(check: Callable[[], Awaitable[bool]], timeout_s: float = 5) -> None:
    for _ in range(int(timeout_s / 0.05)):
        if await check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


def test_worker_survives_run_job_raising(
    jobs_db: str,
    sync_engine: Engine,
    request: pytest.FixtureRequest,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker(request)
    calls: list[UUID] = []

    async def run_job_failing_once(
        engine: AsyncEngine, job: q.ClaimedJob, lease: LeaseSettings
    ) -> str:
        calls.append(job.id)
        if len(calls) == 1:
            raise OSError("database went away")
        return await run_job(engine, job, lease)

    monkeypatch.setattr(main_worker, "run_job", run_job_failing_once)

    async def scenario(engine: AsyncEngine) -> list[UUID]:
        ids = [await _enqueue(engine, OkPayload(marker=marker)) for _ in range(2)]
        stop = asyncio.Event()
        worker = _start_worker(engine, jobs_db, stop)

        async def next_job_ran() -> bool:
            return await _status(engine, ids[1]) == "succeeded"

        await _wait_for(next_job_ran)
        assert not worker.done()
        stop.set()
        await asyncio.wait_for(worker, timeout=2)
        return ids

    with caplog.at_level(logging.INFO):
        ids = _with_engine(jobs_db, scenario)
    assert [r.getMessage() for r in caplog.records].count("worker.job_error") == 1
    assert calls == ids
    assert _row(sync_engine, ids[1])["status"] == "succeeded"


def test_worker_stop_releases_the_running_job(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> tuple[UUID, float]:
        job_id = await _enqueue(engine, LongPayload(marker=marker, sleep_s=4))
        stop = asyncio.Event()
        worker = _start_worker(engine, jobs_db, stop)

        async def running() -> bool:
            return await _status(engine, job_id) == "running"

        await _wait_for(running)
        started = asyncio.get_running_loop().time()
        stop.set()
        await asyncio.wait_for(worker, timeout=2)
        return job_id, asyncio.get_running_loop().time() - started

    job_id, elapsed = _with_engine(jobs_db, scenario)
    assert elapsed < 1
    row = _row(sync_engine, job_id)
    assert (row["status"], row["attempts"], row["lease_owner"]) == ("queued", 0, None)
    assert CALLS[marker] == 0


def test_handler_raising_cancelled_error_is_a_failure(
    jobs_db: str, sync_engine: Engine, request: pytest.FixtureRequest
) -> None:
    marker = _marker(request)

    async def scenario(engine: AsyncEngine) -> UUID:
        bad = await _enqueue(engine, SelfCancelPayload(marker=marker))
        good = await _enqueue(engine, OkPayload(marker=marker))
        stop = asyncio.Event()
        worker = _start_worker(engine, jobs_db, stop)

        async def good_done() -> bool:
            return await _status(engine, good) == "succeeded"

        await _wait_for(good_done)
        assert not worker.done()
        stop.set()
        await asyncio.wait_for(worker, timeout=2)
        return bad

    bad = _with_engine(jobs_db, scenario)
    row = _row(sync_engine, bad)
    assert (row["status"], row["attempts"], row["last_error"]) == (
        "failed_retrying",
        1,
        "CancelledError",
    )
    assert row["lease_owner"] is None
    assert CALLS[marker] == 2  # the self-cancelling handler once, then the ok job


def test_worker_stop_after_the_handler_returned_still_records_success(
    jobs_db: str,
    sync_engine: Engine,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker(request)
    real_complete = q.complete
    finishing = asyncio.Event()

    async def slow_complete(engine: AsyncEngine, job: q.ClaimedJob) -> bool:
        finishing.set()
        await asyncio.sleep(0.3)
        return await real_complete(engine, job)

    monkeypatch.setattr(q, "complete", slow_complete)

    async def scenario(engine: AsyncEngine) -> UUID:
        job_id = await _enqueue(engine, OkPayload(marker=marker))
        stop = asyncio.Event()
        worker = _start_worker(engine, jobs_db, stop)
        await asyncio.wait_for(finishing.wait(), timeout=5)
        stop.set()  # lands while the finish write is in flight
        await asyncio.wait_for(worker, timeout=2)
        return job_id

    job_id = _with_engine(jobs_db, scenario)
    row = _row(sync_engine, job_id)
    assert (row["status"], row["attempts"], row["lease_owner"]) == ("succeeded", 1, None)
    assert CALLS[marker] == 1
