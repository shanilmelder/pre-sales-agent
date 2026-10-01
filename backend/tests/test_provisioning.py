"""First-sign-in provisioning and `GET /api/v1/me` against a real, migrated Postgres."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.identity.application.provisioning import provision_or_load
from app.modules.identity.application.public import TokenIdentity
from app.platform.uow import UnitOfWork, get_uow, unit_of_work
from tests.auth_tokens import NAME_CLAIM, StubJWKSClient, auth_app, bearer, claims, make_token
from tests.conftest import make_client, run_async


def _new_sub() -> str:
    return f"auth0|{uuid4().hex}"


def _users(engine: Engine, sub: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text("SELECT * FROM identity_users WHERE auth0_sub = :s"), {"s": sub}
            ).mappings()
        ]


def _events(engine: Engine, user_id: UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events "
                    "WHERE subject_type = 'identity.user' AND subject_id = :u"
                ),
                {"u": user_id},
            ).mappings()
        ]


def test_first_token_provisions_once_and_returning_user_is_not_reprovisioned(
    db_url: str, sync_engine: Engine
) -> None:
    sub = _new_sub()
    token = make_token(claims(sub))
    with make_client(auth_app(db_url)) as client:
        first = client.get("/api/v1/me", headers=bearer(token))
        second = client.get("/api/v1/me", headers=bearer(token))

    assert first.status_code == 200, first.text
    assert second.status_code == 200
    body = first.json()
    assert body["name"] == "Test Person"
    assert body["email"] == "person@example.test"
    assert body["roles"] == []
    assert second.json() == body

    users = _users(sync_engine, sub)
    assert len(users) == 1
    user = users[0]
    assert str(user["id"]) == body["id"]
    assert user["id"].version == 7
    assert user["row_version"] == 1

    events = _events(sync_engine, user["id"])
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "identity.user.provisioned"
    assert (event["actor_type"], event["actor_id"]) == ("user", body["id"])
    assert event["opportunity_id"] is None
    assert event["payload"] == {}


def test_missing_name_claim_falls_back_to_email(db_url: str, sync_engine: Engine) -> None:
    sub = _new_sub()
    token = make_token(claims(sub, **{NAME_CLAIM: None}))
    with make_client(auth_app(db_url)) as client:
        resp = client.get("/api/v1/me", headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "person@example.test"
    assert _users(sync_engine, sub)[0]["name"] == "person@example.test"


def test_assigned_role_is_returned_on_next_request(db_url: str, sync_engine: Engine) -> None:
    sub = _new_sub()
    token = make_token(claims(sub))
    with make_client(auth_app(db_url)) as client:
        user_id = client.get("/api/v1/me", headers=bearer(token)).json()["id"]
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO identity_user_roles (user_id, role) VALUES (:u, :r)"),
                [{"u": user_id, "r": "presales_engineer"}, {"u": user_id, "r": "retired_role"}],
            )
        resp = client.get("/api/v1/me", headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["presales_engineer"]


def test_token_is_validated_before_the_unit_of_work_opens(db_url: str) -> None:
    keys = StubJWKSClient()
    app = auth_app(db_url, keys)

    async def recording_uow(request: Request) -> AsyncIterator[UnitOfWork]:
        keys.on_fetch.append("uow")
        async for uow in get_uow(request):
            yield uow

    app.dependency_overrides[get_uow] = recording_uow
    with make_client(app) as client:
        resp = client.get("/api/v1/me", headers=bearer(make_token(claims(_new_sub()))))
    assert resp.status_code == 200
    assert keys.on_fetch == ["jwks", "uow"]


def test_concurrent_first_requests_create_one_user_and_one_event(
    db_url: str, sync_engine: Engine
) -> None:
    identity = TokenIdentity(sub=_new_sub(), name="Racer", email="racer@example.test")

    async def scenario() -> tuple[UUID, UUID, bool]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        provisioned = asyncio.Event()
        release = asyncio.Event()

        async def first() -> UUID:
            async with unit_of_work(engine) as uow:
                user = await provision_or_load(uow, identity)
                provisioned.set()
                await release.wait()  # keep the insert uncommitted while `second` races
            return user.id

        async def second() -> UUID:
            await provisioned.wait()
            async with unit_of_work(engine) as uow:
                return (await provision_or_load(uow, identity)).id

        try:
            t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
            await provisioned.wait()
            await asyncio.sleep(0.5)
            second_blocked = not t2.done()  # waiting on the uncommitted unique key
            release.set()
            a, b = await asyncio.gather(t1, t2)
            return a, b, second_blocked
        finally:
            await engine.dispose()

    a, b, second_blocked = run_async(scenario())
    assert a == b
    assert second_blocked
    users = _users(sync_engine, identity.sub)
    assert len(users) == 1
    assert len(_events(sync_engine, users[0]["id"])) == 1


@pytest.mark.parametrize("table", ["identity_users", "identity_user_roles"])
def test_app_role_has_dml_on_identity_tables(sync_engine: Engine, table: str) -> None:
    with sync_engine.connect() as conn:
        granted: dict[str, bool] = {
            p: conn.execute(
                sa.text("SELECT has_table_privilege(:t, :p)"), {"t": table, "p": p}
            ).scalar_one()
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
    assert all(granted.values()), granted
