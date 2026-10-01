"""Unit of Work (AD-25): commit once after the handler returns, roll back on any error."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.platform import trace
from app.platform.actor import Actor
from app.platform.errors import ForbiddenError
from app.platform.ids import new_id
from app.platform.trace.catalogue import IdentityUserProvisioned
from app.platform.uow import UnitOfWork, UoW, unit_of_work
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem

SYSTEM = Actor("system", "test")


def _rows_for(engine: Engine, subject_id: UUID) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM platform_trace_events WHERE subject_id = :s"),
            {"s": subject_id},
        ).scalar_one()


async def _append(uow: UnitOfWork, subject_id: UUID) -> None:
    await trace.append(
        uow,
        actor=SYSTEM,
        payload=IdentityUserProvisioned(),
        subject_type="identity.user",
        subject_id=subject_id,
    )


def test_unit_of_work_has_no_public_commit() -> None:
    assert not hasattr(UnitOfWork, "commit")


def _add_routes(app: FastAPI) -> None:
    @app.post("/api/v1/test/ok/{subject_id}")
    async def ok(subject_id: UUID, uow: UoW) -> dict[str, str]:
        await _append(uow, subject_id)
        return {"status": "ok"}

    @app.post("/api/v1/test/forbidden/{subject_id}")
    async def forbidden(subject_id: UUID, uow: UoW) -> None:
        await _append(uow, subject_id)
        raise ForbiddenError()

    @app.post("/api/v1/test/boom/{subject_id}")
    async def boom(subject_id: UUID, uow: UoW) -> None:
        await _append(uow, subject_id)
        raise RuntimeError("boom")


def test_request_success_commits(db_app: FastAPI, sync_engine: Engine) -> None:
    _add_routes(db_app)
    subject = new_id()
    with make_client(db_app) as client:
        resp = client.post(f"/api/v1/test/ok/{subject}")
    assert resp.status_code == 200
    assert _rows_for(sync_engine, subject) == 1


@pytest.mark.parametrize(
    ("route", "status", "code"),
    [("forbidden", 403, "forbidden"), ("boom", 500, "internal_error")],
)
def test_request_error_rolls_back_including_trace(
    db_app: FastAPI, sync_engine: Engine, route: str, status: int, code: str
) -> None:
    _add_routes(db_app)
    subject = new_id()
    with make_client(db_app) as client:
        resp = client.post(f"/api/v1/test/{route}/{subject}")
    assert resp.status_code == status
    assert resp.headers["content-type"] == "application/problem+json"
    assert_problem(resp.json(), status, code)
    assert _rows_for(sync_engine, subject) == 0


def test_unit_of_work_context_commits_or_rolls_back(db_url: str, sync_engine: Engine) -> None:
    kept, dropped = new_id(), new_id()

    async def scenario() -> None:
        engine = create_async_engine(db_url)
        try:
            async with unit_of_work(engine) as uow:
                await _append(uow, kept)
            with pytest.raises(ValueError, match="nope"):
                async with unit_of_work(engine) as uow:
                    await _append(uow, dropped)
                    raise ValueError("nope")
        finally:
            await engine.dispose()

    run_async(scenario())
    assert _rows_for(sync_engine, kept) == 1
    assert _rows_for(sync_engine, dropped) == 0


def test_app_engine_sessions_run_in_utc(db_app: FastAPI) -> None:
    @db_app.get("/api/v1/test/now")
    async def now(uow: UoW) -> dict[str, str]:
        result = await uow.session.execute(sa.text("SELECT now(), current_setting('TimeZone')"))
        value: datetime
        tz: str
        value, tz = result.one()
        return {"now": value.isoformat(), "tz": tz}

    with make_client(db_app) as client:
        resp = client.get("/api/v1/test/now")
    assert resp.status_code == 200
    assert datetime.fromisoformat(resp.json()["now"]).utcoffset() == timedelta(0)
    # "UTC" (set by create_engine), not merely a server default such as "Etc/UTC".
    assert resp.json()["tz"] == "UTC"
