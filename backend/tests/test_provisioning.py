"""First-sign-in provisioning and `GET /api/v1/me` against a real, migrated Postgres."""

import asyncio
import json
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
from tests.auth_tokens import (
    NAME_CLAIM,
    PERMISSIONS_CLAIM,
    ROLES_CLAIM,
    StubJWKSClient,
    auth_app,
    bearer,
    claims,
    make_token,
)
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
    assert body["permissions"] == []
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


def _cached_roles(engine: Engine, user_id: str) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text("SELECT role FROM identity_user_roles WHERE user_id = :u ORDER BY role"),
                {"u": user_id},
            ).scalars()
        )


def _ignored_claims_logs(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    return [r for r in records if r.get("event") == "identity.claim_values_ignored"]


def test_roles_and_permissions_come_from_the_token(db_url: str, sync_engine: Engine) -> None:
    token = make_token(
        claims(
            _new_sub(),
            **{
                ROLES_CLAIM: ["presales_engineer", "commercial"],
                PERMISSIONS_CLAIM: ["opportunities.opportunity.create", "identity.user.search"],
            },
        )
    )
    with make_client(auth_app(db_url)) as client:
        body = client.get("/api/v1/me", headers=bearer(token)).json()
    assert body["roles"] == ["commercial", "presales_engineer"]
    assert body["permissions"] == ["identity.user.search", "opportunities.opportunity.create"]
    assert _cached_roles(sync_engine, body["id"]) == ["commercial", "presales_engineer"]


def test_absent_claims_grant_nothing_and_are_not_a_401(db_url: str, sync_engine: Engine) -> None:
    with make_client(auth_app(db_url)) as client:
        resp = client.get("/api/v1/me", headers=bearer(make_token(claims(_new_sub()))))
    assert resp.status_code == 200
    assert (resp.json()["roles"], resp.json()["permissions"]) == ([], [])
    assert _cached_roles(sync_engine, resp.json()["id"]) == []


@pytest.mark.parametrize(
    ("roles", "permissions"),
    [
        (["intern", "commercial"], ["foo.bar.baz", "identity.user.list"]),
        (["commercial", 7, None], ["identity.user.list", {"x": 1}]),  # non-strings
    ],
    ids=["unknown-values", "malformed-items"],
)
def test_unknown_or_malformed_values_are_ignored_and_logged(
    db_url: str, capsys: pytest.CaptureFixture[str], roles: list[Any], permissions: list[Any]
) -> None:
    token = make_token(claims(_new_sub(), **{ROLES_CLAIM: roles, PERMISSIONS_CLAIM: permissions}))
    with make_client(auth_app(db_url)) as client:
        resp = client.get("/api/v1/me", headers=bearer(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["roles"] == ["commercial"]
    assert resp.json()["permissions"] == ["identity.user.list"]
    (record,) = _ignored_claims_logs(capsys)
    assert record["level"] == "warning"
    assert record["user_id"] == resp.json()["id"]


@pytest.mark.parametrize("value", ["presales_engineer", {"a": 1}, 42])
def test_claim_that_is_not_a_list_grants_nothing(
    db_url: str, capsys: pytest.CaptureFixture[str], value: Any
) -> None:
    token = make_token(claims(_new_sub(), **{ROLES_CLAIM: value, PERMISSIONS_CLAIM: value}))
    with make_client(auth_app(db_url)) as client:
        resp = client.get("/api/v1/me", headers=bearer(token))
    assert resp.status_code == 200
    assert (resp.json()["roles"], resp.json()["permissions"]) == ([], [])
    (record,) = _ignored_claims_logs(capsys)
    assert record["malformed_claims"] == [ROLES_CLAIM, PERMISSIONS_CLAIM]


def test_role_change_takes_effect_with_the_next_token(db_url: str, sync_engine: Engine) -> None:
    sub = _new_sub()
    with make_client(auth_app(db_url)) as client:
        first = client.get(
            "/api/v1/me", headers=bearer(make_token(claims(sub, **{ROLES_CLAIM: ["commercial"]})))
        )
        user_id = first.json()["id"]
        assert _cached_roles(sync_engine, user_id) == ["commercial"]
        second = client.get("/api/v1/me", headers=bearer(make_token(claims(sub))))
    assert second.json()["roles"] == []
    assert _cached_roles(sync_engine, user_id) == []


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
