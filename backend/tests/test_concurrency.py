"""Optimistic concurrency (AD-11): `row_version`, `If-Match`, 428 and 412."""

from dataclasses import dataclass
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Response
from sqlalchemy import Text, Uuid
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.main_api import create_app
from app.platform import trace
from app.platform.actor import Actor
from app.platform.concurrency import IfMatch, RowVersioned, check_row_version, etag, parse_if_match
from app.platform.config import Settings
from app.platform.errors import IfMatchRequiredError, RowVersionMismatchError
from app.platform.ids import new_id
from app.platform.trace.catalogue import IdentityUserProvisioned
from app.platform.uow import UnitOfWork, UoW
from tests.conftest import UNREACHABLE_DB, make_client
from tests.test_health import assert_problem

# --- pure helpers ------------------------------------------------------------------------


def test_etag_round_trips() -> None:
    assert etag(3) == '"3"'
    assert parse_if_match(etag(3)) == 3
    assert parse_if_match(" 12 ") == 12


@pytest.mark.parametrize("header", [None, "", "   "])
def test_missing_if_match_is_428(header: str | None) -> None:
    with pytest.raises(IfMatchRequiredError):
        parse_if_match(header)


@pytest.mark.parametrize("header", ["*", '"03"', "007", 'W/"3"', '"3", "4"', '"abc"', '"-1"', "x"])
def test_unparseable_if_match_is_412(header: str) -> None:
    with pytest.raises(RowVersionMismatchError):
        parse_if_match(header)


@dataclass
class _Row:
    row_version: int


def test_check_row_version() -> None:
    check_row_version(4, _Row(4))
    with pytest.raises(RowVersionMismatchError):
        check_row_version(3, _Row(4))


# --- If-Match through HTTP (no DB) --------------------------------------------------------


@pytest.fixture
def if_match_app() -> FastAPI:
    app = create_app(Settings(database_url=UNREACHABLE_DB))

    @app.patch("/api/v1/test/thing")
    async def patch_thing(expected: IfMatch, response: Response) -> dict[str, int]:
        check_row_version(expected, _Row(4))
        response.headers["ETag"] = etag(5)
        return {"row_version": 5}

    return app


def test_write_without_if_match_is_428(if_match_app: FastAPI) -> None:
    with make_client(if_match_app) as client:
        resp = client.patch("/api/v1/test/thing")
    assert resp.status_code == 428
    assert resp.headers["content-type"] == "application/problem+json"
    assert_problem(resp.json(), 428, "if_match_required")


def test_stale_if_match_is_412(if_match_app: FastAPI) -> None:
    with make_client(if_match_app) as client:
        resp = client.patch("/api/v1/test/thing", headers={"If-Match": '"3"'})
    assert resp.status_code == 412
    assert_problem(resp.json(), 412, "row_version_mismatch")


def test_current_if_match_succeeds(if_match_app: FastAPI) -> None:
    with make_client(if_match_app) as client:
        resp = client.patch("/api/v1/test/thing", headers={"If-Match": '"4"'})
    assert resp.status_code == 200
    assert resp.headers["ETag"] == '"5"'


# --- versioned rows against Postgres (temporary table) -------------------------------------


class _TestBase(DeclarativeBase):
    pass


class Item(RowVersioned, _TestBase):
    __tablename__ = "test_versioned_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


_CREATE_TEMP = sa.text(
    "CREATE TEMP TABLE test_versioned_items "
    "(id uuid PRIMARY KEY, name text NOT NULL, row_version integer NOT NULL) ON COMMIT DROP"
)
_BUMP = sa.text("UPDATE test_versioned_items SET row_version = row_version + 1 WHERE id = :id")


async def _seed(uow: UnitOfWork) -> Item:
    await uow.session.execute(_CREATE_TEMP)
    item = Item(id=new_id(), name="a")
    uow.session.add(item)
    await uow.flush()
    return item


def _trace_rows(engine: Engine, subject_id: UUID) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM platform_trace_events WHERE subject_id = :s"),
            {"s": subject_id},
        ).scalar_one()


def _add_routes(app: FastAPI, returned: list[bool] | None = None) -> None:
    @app.post("/api/v1/test/versioned/seed")
    async def seed(uow: UoW) -> dict[str, int]:
        item = await _seed(uow)
        first = item.row_version
        item.name = "b"
        await uow.flush()
        return {"first": first, "second": item.row_version}

    @app.post("/api/v1/test/versioned/race-at-commit/{subject_id}")
    async def race_at_commit(subject_id: UUID, uow: UoW) -> None:
        item = await _seed(uow)
        await uow.session.execute(_BUMP, {"id": item.id})  # a concurrent writer wins
        # Append first: its ORM-enabled insert autoflushes, so mutating `item` before it
        # would raise StaleDataError here instead of at the edge's commit.
        await trace.append(
            uow,
            actor=Actor("system", "test"),
            payload=IdentityUserProvisioned(),
            subject_type="test.item",
            subject_id=subject_id,
        )
        item.name = "b"  # flushed only by the edge's commit in get_uow -> StaleDataError
        if returned is not None:
            returned.append(True)

    @app.patch("/api/v1/test/versioned/if-match/{subject_id}")
    async def if_match_write(subject_id: UUID, expected: IfMatch, uow: UoW) -> None:
        item = await _seed(uow)
        for _ in range(3):  # row now at version 4
            await uow.session.execute(_BUMP, {"id": item.id})
        await uow.session.refresh(item)
        check_row_version(expected, item)
        item.name = "b"
        await trace.append(
            uow,
            actor=Actor("system", "test"),
            payload=IdentityUserProvisioned(),
            subject_type="test.item",
            subject_id=subject_id,
            subject_version=item.row_version,
        )


def test_row_version_starts_at_1_and_increments(db_app: FastAPI) -> None:
    _add_routes(db_app)
    with make_client(db_app) as client:
        resp = client.post("/api/v1/test/versioned/seed")
    assert resp.status_code == 200
    assert resp.json() == {"first": 1, "second": 2}


def test_concurrent_update_at_commit_is_412_and_writes_nothing(
    db_app: FastAPI, sync_engine: Engine
) -> None:
    returned: list[bool] = []
    _add_routes(db_app, returned)
    subject = new_id()
    with make_client(db_app) as client:
        resp = client.post(f"/api/v1/test/versioned/race-at-commit/{subject}")
    assert returned == [True], "the handler must return; the failure belongs to the commit"
    assert resp.status_code == 412
    assert resp.headers["content-type"] == "application/problem+json"
    assert_problem(resp.json(), 412, "row_version_mismatch")
    assert _trace_rows(sync_engine, subject) == 0


def test_if_match_mismatch_against_db_row_is_412_and_writes_nothing(
    db_app: FastAPI, sync_engine: Engine
) -> None:
    _add_routes(db_app)
    subject = new_id()
    with make_client(db_app) as client:
        stale = client.patch(
            f"/api/v1/test/versioned/if-match/{subject}", headers={"If-Match": '"3"'}
        )
        missing = client.patch(f"/api/v1/test/versioned/if-match/{subject}")
    assert stale.status_code == 412
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert missing.status_code == 428
    assert_problem(missing.json(), 428, "if_match_required")
    assert _trace_rows(sync_engine, subject) == 0


def test_if_match_current_against_db_row_commits(db_app: FastAPI, sync_engine: Engine) -> None:
    _add_routes(db_app)
    subject = new_id()
    with make_client(db_app) as client:
        resp = client.patch(
            f"/api/v1/test/versioned/if-match/{subject}", headers={"If-Match": '"4"'}
        )
    assert resp.status_code == 200
    assert _trace_rows(sync_engine, subject) == 1
