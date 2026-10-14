"""Workflow progress and the per-Opportunity event stream (Story 5.2) against a real,
migrated Postgres as psa_app: progress rows and their grants, the SSE frames, replay from
`Last-Event-ID`, the route's authorization, the daily prune from `platform_schedules`, and the
0028 migration's round trip with existing runs.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.workflows.application import events
from app.modules.workflows.application import progress as workflows_progress
from app.modules.workflows.domain.runs import AssessmentRunStatus, AssessmentTaskStatus
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.schedules import enqueue_due
from app.platform.uow import unit_of_work
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_gaps_detection import rows
from tests.test_intake_extraction import BASE, FakeGateway, owner
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import PSE, _user
from tests.test_orchestration import planned

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

PRUNE = "workflows.prune_progress"


async def _record(db_url: str, opp_id: str, run_id: UUID, status: AssessmentRunStatus) -> UUID:
    """A run progress row, written as the run commands write them; returns its id."""
    engine = create_engine(Settings(database_url=db_url))
    try:
        async with unit_of_work(engine) as uow:
            await workflows_progress.run_changed(
                uow, opportunity_id=UUID(opp_id), run_id=run_id, status=status
            )
            latest: UUID = (
                await uow.session.execute(
                    sa.text(
                        "SELECT id FROM workflows_progress WHERE run_id = :r "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"r": run_id},
                )
            ).scalar_one()
        return latest
    finally:
        await engine.dispose()


async def _next_frame(stream: AsyncIterator[str]) -> str:
    """The next frame that is not a comment line."""
    async with asyncio.timeout(10):
        while True:
            chunk = await anext(stream)
            if not chunk.startswith(":"):
                return chunk


def _parse(frame: str) -> tuple[str, str, dict[str, Any]]:
    lines = dict(line.split(": ", 1) for line in frame.strip().split("\n"))
    return lines["id"], lines["event"], json.loads(lines["data"])


# --- the stream -----------------------------------------------------------------------------


def test_the_stream_replays_after_the_last_event_id_then_sends_live_frames(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    _, other = owner(client, sync_engine)
    run_id, _ = planned(db_url, opp["id"])
    other_run, _ = planned(db_url, other["id"])

    async def scenario() -> list[str]:
        first = await _record(db_url, opp["id"], run_id, AssessmentRunStatus.QUEUED)
        second = await _record(db_url, opp["id"], run_id, AssessmentRunStatus.FAILED)
        engine = create_engine(Settings(database_url=db_url))
        stream = events.event_stream(engine, db_url, UUID(opp["id"]), first, keepalive_s=0.2)
        try:
            assert await anext(stream) == ": connected\n\n"
            replayed = await _next_frame(stream)
            await _record(db_url, other["id"], other_run, AssessmentRunStatus.QUEUED)
            third = await _record(db_url, opp["id"], run_id, AssessmentRunStatus.SUCCEEDED)
            live = await _next_frame(stream)
            return [str(second), replayed, str(third), live]
        finally:
            await stream.aclose()
            await engine.dispose()

    second_id, replayed, third_id, live = run_async(scenario())

    event_id, event, data = _parse(replayed)
    assert (event_id, event) == (second_id, "workflows.run.ended")
    assert set(data) == {
        "event_type",
        "subject_type",
        "subject_id",
        "subject_version",
        "occurred_at",
        "summary",
    }
    assert (data["subject_type"], data["subject_id"], data["summary"]) == (
        "workflows.run",
        str(run_id),
        "run failed",
    )
    event_id, event, data = _parse(live)  # the other Opportunity's row was not sent
    assert (event_id, event, data["summary"]) == (third_id, "workflows.run.ended", "run succeeded")


def test_an_unknown_last_event_id_streams_from_now(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    run_id, _ = planned(db_url, opp["id"])

    async def scenario() -> list[str]:
        await _record(db_url, opp["id"], run_id, AssessmentRunStatus.QUEUED)
        engine = create_engine(Settings(database_url=db_url))
        stream = events.event_stream(engine, db_url, UUID(opp["id"]), uuid4(), keepalive_s=0.2)
        try:
            return [await anext(stream), await anext(stream)]
        finally:
            await stream.aclose()
            await engine.dispose()

    assert run_async(scenario()) == [": connected\n\n", ": keep-alive\n\n"]


def test_a_run_writes_progress_for_each_task_start_and_end(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = owner(client, sync_engine)  # no Requirements: no model call
    response = client.post(f"{BASE}/{opp['id']}/assessment-runs", headers=headers)
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]

    assert extraction_tests.drain(db_url, extraction_tests.ASSESS) == ["succeeded"]

    found = rows(
        sync_engine, "SELECT * FROM workflows_progress WHERE run_id = :r ORDER BY id", r=run_id
    )
    kinds = [r["event_type"] for r in found]
    assert kinds[0] == "workflows.run.queued"
    assert kinds[-1] == "workflows.run.ended"
    assert kinds.count("workflows.task.started") == 3
    assert kinds.count("workflows.task.ended") == 3
    assert {r["opportunity_id"] for r in found} == {UUID(opp["id"])}
    summaries = {r["summary"] for r in found}
    assert {"engineering_agent running", "pm_agent succeeded", "run succeeded"} <= summaries
    for row in found:  # Agent ids and statuses only
        words = row["summary"].split()
        assert len(words) == 2
        assert words[1] in {s.value for s in AssessmentTaskStatus} | {
            s.value for s in AssessmentRunStatus
        }


def test_progress_rows_are_not_updatable_by_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    run_id, _ = planned(db_url, opp["id"])
    run_async(_record(db_url, opp["id"], run_id, AssessmentRunStatus.QUEUED))
    for sql in (
        "UPDATE workflows_progress SET summary = 'x' WHERE run_id = :r",
        "UPDATE workflows_runs SET plan_version = 2 WHERE id = :r",
        "UPDATE workflows_tasks SET requires = '{}' WHERE run_id = :r",
        "INSERT INTO platform_schedules (name, job_type, interval_s) VALUES ('x', 'x.y', 1)",
        "UPDATE platform_schedules SET job_type = 'x.y' WHERE false",
    ):
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"r": run_id})


# --- the route ------------------------------------------------------------------------------


def test_the_route_streams_to_a_reader_and_passes_the_last_event_id(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = owner(client, sync_engine)
    seen: list[UUID | None] = []
    resume = uuid4()

    async def finite(
        engine: Any, database_url: str, opportunity_id: UUID, last_event_id: UUID | None
    ) -> AsyncIterator[str]:
        seen.append(last_event_id)
        yield ": connected\n\n"
        yield 'id: 1\nevent: workflows.run.queued\ndata: {"summary": "run queued"}\n\n'

    monkeypatch.setattr(events, "event_stream", finite)

    response = client.get(
        f"{BASE}/{opp['id']}/events", headers={**headers, "Last-Event-ID": str(resume)}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "event: workflows.run.queued" in response.text
    assert seen == [resume]


def test_the_route_is_404_for_someone_who_cannot_read_the_opportunity(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    stranger, _ = _user(client, sync_engine, "Someone Else", PSE)

    response = client.get(f"{BASE}/{opp['id']}/events", headers=stranger)

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"
    assert client.get(f"{BASE}/{uuid4()}/events", headers=stranger).status_code == 404


# --- pruning --------------------------------------------------------------------------------


def test_the_daily_schedule_enqueues_the_prune_which_deletes_rows_older_than_30_days(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    run_id, _ = planned(db_url, opp["id"])
    old, fresh = uuid4(), uuid4()
    with sync_engine.begin() as conn:
        for row_id, age in ((old, "31 days"), (fresh, "29 days")):
            conn.execute(
                sa.text(
                    "INSERT INTO workflows_progress (id, opportunity_id, run_id, event_type, "
                    "subject_type, subject_id, summary, occurred_at) VALUES (:i, :o, :r, "
                    "'workflows.run.queued', 'workflows.run', :r, 'run queued', "
                    "now() - CAST(:age AS interval))"
                ),
                {"i": row_id, "o": opp["id"], "r": run_id, "age": age},
            )
        conn.execute(
            sa.text(
                "UPDATE platform_schedules SET next_run_at = now() - interval '1 minute' "
                "WHERE name = :n"
            ),
            {"n": PRUNE},
        )

    async def scenario() -> tuple[list[str], list[str]]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            first = await enqueue_due(engine)
            second = await enqueue_due(engine)  # not due again for a day
            await workflows_progress.prune_progress(
                JobContext(
                    job_id=uuid4(),
                    job_type=PRUNE,
                    attempt=1,
                    max_attempts=3,
                    opportunity_id=None,
                    engine=engine,
                ),
                workflows_progress.PruneProgress(),
            )
            return first, second
        finally:
            await engine.dispose()

    try:
        first, second = run_async(scenario())
        assert PRUNE in first
        assert PRUNE not in second
        (schedule,) = rows(sync_engine, "SELECT * FROM platform_schedules WHERE name = :n", n=PRUNE)
        assert schedule["interval_s"] == 86400
        assert schedule["last_enqueued_at"] is not None
        jobs = rows(
            sync_engine,
            "SELECT * FROM platform_jobs WHERE job_type = :t AND status = 'queued'",
            t=PRUNE,
        )
        assert len(jobs) >= 1
        assert jobs[-1]["payload"] == {}
        left = {r["id"] for r in rows(sync_engine, "SELECT id FROM workflows_progress")}
        assert fresh in left
        assert old not in left
    finally:
        with sync_engine.begin() as conn:  # no other claimer ever runs these
            conn.execute(
                sa.text(
                    "UPDATE platform_jobs SET status = 'dead', last_error = 'test: not run' "
                    "WHERE job_type = :t AND status = 'queued'"
                ),
                {"t": PRUNE},
            )


# --- the migration --------------------------------------------------------------------------


def test_the_migration_keeps_existing_runs_through_a_downgrade_and_upgrade(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = owner(client, sync_engine)
    started = client.post(f"{BASE}/{opp['id']}/assessment-runs", headers=headers)
    assert started.status_code == 201, started.text
    run = started.json()

    _alembic("downgrade", "0027_registry_eval_results")
    try:
        old_runs = rows(sync_engine, "SELECT * FROM assessments_runs WHERE id = :r", r=run["id"])
        assert [str(r["id"]) for r in old_runs] == [run["id"]]
        old_tasks = rows(
            sync_engine, "SELECT * FROM assessments_tasks WHERE run_id = :r", r=run["id"]
        )
        assert len(old_tasks) == 3
        (job,) = rows(
            sync_engine,
            "SELECT job_type FROM platform_jobs WHERE opportunity_id = :o",
            o=opp["id"],
        )
        assert job["job_type"] == "assessments.run_assessment"
    finally:
        _alembic("upgrade", "head")

    view = client.get(f"{BASE}/{opp['id']}/assessments", headers=headers)
    assert view.status_code == 200, view.text
    assert view.json()["run"]["id"] == run["id"]
    assert [t["status"] for t in view.json()["run"]["tasks"]] == ["queued"] * 3
    (job,) = rows(
        sync_engine, "SELECT job_type FROM platform_jobs WHERE opportunity_id = :o", o=opp["id"]
    )
    assert job["job_type"] == "workflows.execute"
