"""Users & roles administration (Story 1.6) against a real, migrated Postgres as psa_app.

Covers the spec's I/O matrix: assign, remove, no-op, stale (412), missing If-Match (428),
last administrator (409), the concurrent-removal race, non-admins (403), unknown role or
user (422/404) and the next-request effect on `/me`.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.identity.adapters import repository
from app.modules.identity.application.public import (
    LAST_ADMINISTRATOR_DETAIL,
    Principal,
    Role,
    remove_role,
)
from app.platform.actor import Actor
from app.platform.errors import LastAdministratorError
from app.platform.uow import unit_of_work
from tests.auth_tokens import EMAIL_CLAIM, NAME_CLAIM, auth_app, bearer, claims, make_token
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem

ADMIN = "platform_administrator"
BASE = "/api/v1/admin/users"


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _signed_in(client: TestClient, name: str) -> tuple[dict[str, str], UUID]:
    """Provision a fresh user through `/me`; returns their auth headers and id."""
    sub = f"auth0|{uuid4().hex}"
    token = make_token(claims(sub, **{NAME_CLAIM: name, EMAIL_CLAIM: f"{uuid4().hex}@ex.test"}))
    headers = bearer(token)
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return headers, UUID(resp.json()["id"])


def _grant(engine: Engine, user_id: UUID, *roles: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO identity_user_roles (user_id, role) VALUES (:u, :r)"),
            [{"u": user_id, "r": role} for role in roles],
        )


def _admin(
    client: TestClient, engine: Engine, name: str = "Admin Person"
) -> tuple[dict[str, str], UUID]:
    headers, user_id = _signed_in(client, name)
    _grant(engine, user_id, ADMIN)
    return headers, user_id


def _row_version(engine: Engine, user_id: UUID) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT row_version FROM identity_users WHERE id = :u"), {"u": user_id}
        ).scalar_one()


def _roles(engine: Engine, user_id: UUID) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text("SELECT role FROM identity_user_roles WHERE user_id = :u ORDER BY role"),
                {"u": user_id},
            ).scalars()
        )


def _role_events(engine: Engine, user_id: UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE subject_type = 'identity.user' "
                    "AND subject_id = :u AND event_type LIKE 'identity.user.role_%' "
                    "ORDER BY occurred_at, id"
                ),
                {"u": user_id},
            ).mappings()
        ]


@contextmanager
def _only_admins(engine: Engine, *keep: UUID) -> Iterator[None]:
    """Temporarily leave only `keep` holding `platform_administrator` (the test database is
    shared with other tests); the other grants are restored afterwards."""
    with engine.begin() as conn:
        others = list(
            conn.execute(
                sa.text(
                    "DELETE FROM identity_user_roles WHERE role = :r "
                    "AND NOT (user_id = ANY(:keep)) RETURNING user_id"
                ),
                {"r": ADMIN, "keep": list(keep)},
            ).scalars()
        )
    try:
        yield
    finally:
        if others:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO identity_user_roles (user_id, role) VALUES (:u, :r) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    [{"u": u, "r": ADMIN} for u in others],
                )


def _if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


# --- assign ---------------------------------------------------------------------------------


def test_assign_adds_role_bumps_version_traces_and_applies_on_next_request(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, admin_id = _admin(client, sync_engine, "Admin Assigner")
    target_headers, target_id = _signed_in(client, "Target Person")
    before = _row_version(sync_engine, target_id)

    resp = client.put(
        f"{BASE}/{target_id}/roles/pm_reviewer",
        headers={**admin_headers, **_if_match(before)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(target_id)
    assert body["roles"] == ["pm_reviewer"]
    assert body["row_version"] == before + 1
    assert body["last_changed_by"] == "Admin Assigner"
    assert resp.headers["ETag"] == f'"{before + 1}"'
    assert _row_version(sync_engine, target_id) == before + 1

    events = _role_events(sync_engine, target_id)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "identity.user.role_assigned"
    assert (event["actor_type"], event["actor_id"]) == ("user", str(admin_id))
    assert event["subject_version"] == before + 1
    assert event["opportunity_id"] is None
    assert event["payload"] == {"role": "pm_reviewer"}

    me = client.get("/api/v1/me", headers=target_headers)
    assert me.json()["roles"] == ["pm_reviewer"]


def test_assign_held_role_is_a_noop(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    _grant(sync_engine, target_id, "commercial")
    version = _row_version(sync_engine, target_id)

    resp = client.put(
        f"{BASE}/{target_id}/roles/commercial", headers={**admin_headers, **_if_match(version)}
    )

    assert resp.status_code == 200
    assert resp.json()["roles"] == ["commercial"]
    assert resp.json()["row_version"] == version
    assert resp.headers["ETag"] == f'"{version}"'
    assert _row_version(sync_engine, target_id) == version
    assert _role_events(sync_engine, target_id) == []


# --- remove ---------------------------------------------------------------------------------


def test_remove_takes_role_bumps_version_and_traces(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, admin_id = _admin(client, sync_engine)
    target_headers, target_id = _signed_in(client, "Target Person")
    _grant(sync_engine, target_id, "pm_reviewer", "commercial")
    before = _row_version(sync_engine, target_id)

    resp = client.delete(
        f"{BASE}/{target_id}/roles/pm_reviewer", headers={**admin_headers, **_if_match(before)}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["roles"] == ["commercial"]
    assert resp.json()["row_version"] == before + 1
    assert resp.headers["ETag"] == f'"{before + 1}"'
    assert _roles(sync_engine, target_id) == ["commercial"]
    events = _role_events(sync_engine, target_id)
    assert [
        (e["event_type"], e["payload"], e["actor_id"], e["subject_version"]) for e in events
    ] == [("identity.user.role_removed", {"role": "pm_reviewer"}, str(admin_id), before + 1)]
    assert client.get("/api/v1/me", headers=target_headers).json()["roles"] == ["commercial"]


def test_remove_missing_role_is_a_noop(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    version = _row_version(sync_engine, target_id)

    resp = client.delete(
        f"{BASE}/{target_id}/roles/security_reviewer",
        headers={**admin_headers, **_if_match(version)},
    )

    assert resp.status_code == 200
    assert resp.json()["roles"] == []
    assert resp.json()["row_version"] == version
    assert _row_version(sync_engine, target_id) == version
    assert _role_events(sync_engine, target_id) == []


def test_removing_another_admin_is_allowed_when_one_remains(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, admin_id = _admin(client, sync_engine)
    _, other_id = _admin(client, sync_engine, "Other Admin")
    with _only_admins(sync_engine, admin_id, other_id):
        version = _row_version(sync_engine, other_id)
        resp = client.delete(
            f"{BASE}/{other_id}/roles/{ADMIN}", headers={**admin_headers, **_if_match(version)}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["roles"] == []


# --- concurrency ----------------------------------------------------------------------------


def test_stale_if_match_is_412_and_writes_nothing(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    version = _row_version(sync_engine, target_id)
    # Someone else changes the user first.
    first = client.put(
        f"{BASE}/{target_id}/roles/commercial", headers={**admin_headers, **_if_match(version)}
    )
    assert first.status_code == 200

    stale_assign = client.put(
        f"{BASE}/{target_id}/roles/pm_reviewer", headers={**admin_headers, **_if_match(version)}
    )
    stale_remove = client.delete(
        f"{BASE}/{target_id}/roles/commercial", headers={**admin_headers, **_if_match(version)}
    )
    # A no-op on a stale view is still told to reload.
    stale_noop = client.put(
        f"{BASE}/{target_id}/roles/commercial", headers={**admin_headers, **_if_match(version)}
    )

    for resp in (stale_assign, stale_remove, stale_noop):
        assert resp.status_code == 412, resp.text
        assert resp.headers["content-type"] == "application/problem+json"
        assert_problem(resp.json(), 412, "row_version_mismatch")
    assert _roles(sync_engine, target_id) == ["commercial"]
    assert _row_version(sync_engine, target_id) == version + 1
    assert len(_role_events(sync_engine, target_id)) == 1


@pytest.mark.parametrize("method", ["put", "delete"])
def test_write_without_if_match_is_428(
    client: TestClient, sync_engine: Engine, method: str
) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    resp = client.request(method, f"{BASE}/{target_id}/roles/commercial", headers=admin_headers)
    assert resp.status_code == 428
    assert_problem(resp.json(), 428, "if_match_required")
    assert _roles(sync_engine, target_id) == []


# --- last administrator -----------------------------------------------------------------------


def test_removing_own_admin_role_as_the_only_admin_is_409(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, admin_id = _admin(client, sync_engine)
    with _only_admins(sync_engine, admin_id):
        version = _row_version(sync_engine, admin_id)
        resp = client.delete(
            f"{BASE}/{admin_id}/roles/{ADMIN}", headers={**admin_headers, **_if_match(version)}
        )
        assert resp.status_code == 409
        body = resp.json()
        assert_problem(body, 409, "last_administrator")
        assert body["detail"] == "At least one platform administrator is required"
        assert body["detail"] == LAST_ADMINISTRATOR_DETAIL
        assert _roles(sync_engine, admin_id) == [ADMIN]
        assert _row_version(sync_engine, admin_id) == version
        assert _role_events(sync_engine, admin_id) == []


def test_concurrent_mutual_admin_removal_leaves_one_admin(
    db_url: str, client: TestClient, sync_engine: Engine
) -> None:
    _, a_id = _admin(client, sync_engine, "Admin A")
    _, b_id = _admin(client, sync_engine, "Admin B")
    a = Principal(Actor("user", str(a_id)), frozenset({Role.PLATFORM_ADMINISTRATOR}))
    b = Principal(Actor("user", str(b_id)), frozenset({Role.PLATFORM_ADMINISTRATOR}))

    a_version, b_version = _row_version(sync_engine, a_id), _row_version(sync_engine, b_id)

    async def scenario() -> tuple[bool, BaseException | None]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        removed = asyncio.Event()
        release = asyncio.Event()

        async def a_removes_b() -> None:
            async with unit_of_work(engine) as uow:
                await remove_role(uow, a, b_id, Role.PLATFORM_ADMINISTRATOR, f'"{b_version}"')
                removed.set()
                await release.wait()  # hold the admin-grant locks, uncommitted

        async def b_removes_a() -> None:
            await removed.wait()
            async with unit_of_work(engine) as uow:
                await remove_role(uow, b, a_id, Role.PLATFORM_ADMINISTRATOR, f'"{a_version}"')

        try:
            t1, t2 = asyncio.create_task(a_removes_b()), asyncio.create_task(b_removes_a())
            await removed.wait()
            await asyncio.sleep(0.5)
            second_blocked = not t2.done()  # waiting on the admin-grant row lock
            release.set()
            results = await asyncio.gather(t1, t2, return_exceptions=True)
            assert results[0] is None, results[0]
            error = results[1] if isinstance(results[1], BaseException) else None
            return second_blocked, error
        finally:
            await engine.dispose()

    with _only_admins(sync_engine, a_id, b_id):
        second_blocked, error = run_async(scenario())
        assert second_blocked
        assert isinstance(error, LastAdministratorError)
        assert _roles(sync_engine, a_id) == [ADMIN]
        assert _roles(sync_engine, b_id) == []
        assert len(_role_events(sync_engine, b_id)) == 1
        assert _role_events(sync_engine, a_id) == []


# --- authorization and validation -------------------------------------------------------------


def test_non_admin_gets_403_on_every_endpoint(client: TestClient, sync_engine: Engine) -> None:
    headers, user_id = _signed_in(client, "Engineer Person")
    _grant(sync_engine, user_id, "presales_engineer")
    _, target_id = _signed_in(client, "Target Person")
    version = _row_version(sync_engine, target_id)
    responses = [
        client.get(BASE, headers=headers),
        client.get(f"{BASE}/{target_id}", headers=headers),
        client.put(f"{BASE}/{target_id}/roles/{ADMIN}", headers={**headers, **_if_match(version)}),
        client.delete(
            f"{BASE}/{target_id}/roles/{ADMIN}", headers={**headers, **_if_match(version)}
        ),
        # Authorization comes before the If-Match check.
        client.put(f"{BASE}/{target_id}/roles/{ADMIN}", headers=headers),
    ]
    for resp in responses:
        assert resp.status_code == 403, resp.text
        assert_problem(resp.json(), 403, "forbidden")
    assert _roles(sync_engine, target_id) == []
    assert _role_events(sync_engine, target_id) == []


def test_unauthenticated_is_401(client: TestClient) -> None:
    resp = client.get(BASE)
    assert resp.status_code == 401
    assert_problem(resp.json(), 401, "token_missing")


def test_unknown_role_is_422_and_unknown_user_is_404(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    missing = uuid4()

    bad_role = client.put(
        f"{BASE}/{target_id}/roles/superuser", headers={**admin_headers, **_if_match(1)}
    )
    assert bad_role.status_code == 422
    assert_problem(bad_role.json(), 422, "validation_error")

    for resp in (
        client.get(f"{BASE}/{missing}", headers=admin_headers),
        client.put(f"{BASE}/{missing}/roles/commercial", headers={**admin_headers, **_if_match(1)}),
        client.delete(
            f"{BASE}/{missing}/roles/commercial", headers={**admin_headers, **_if_match(1)}
        ),
    ):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")


# --- reads ----------------------------------------------------------------------------------


def test_get_user_returns_roles_and_etag(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    _grant(sync_engine, target_id, "commercial", "pm_reviewer", "retired_role")

    resp = client.get(f"{BASE}/{target_id}", headers=admin_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Target Person"
    assert body["roles"] == ["commercial", "pm_reviewer"]  # unknown stored values are hidden
    assert body["last_changed_by"] is None
    assert resp.headers["ETag"] == f'"{body["row_version"]}"'


def test_list_is_paginated_with_roles(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, admin_id = _admin(client, sync_engine)
    for i in range(3):
        _signed_in(client, f"Listed Person {i}")

    first = client.get(BASE, headers=admin_headers, params={"page_size": 2})
    second = client.get(BASE, headers=admin_headers, params={"page_size": 2, "page": 2})
    default = client.get(BASE, headers=admin_headers)

    assert first.status_code == 200, first.text
    page1, page2 = first.json(), second.json()
    assert (page1["page"], page1["page_size"]) == (1, 2)
    assert page1["total"] >= 4
    assert len(page1["items"]) == 2
    assert {u["id"] for u in page1["items"]}.isdisjoint({u["id"] for u in page2["items"]})
    assert default.json()["page_size"] == 50
    admin = client.get(f"{BASE}/{admin_id}", headers=admin_headers).json()
    assert admin["roles"] == [ADMIN]
    assert set(admin) == {"id", "name", "email", "roles", "row_version", "last_changed_by"}

    for params in (
        {"page": 0},
        {"page": 1_000_001},
        {"page": 2**63},
        {"page_size": 0},
        {"page_size": 201},
    ):
        bad = client.get(BASE, headers=admin_headers, params=params)
        assert bad.status_code == 422, params


def test_trace_payload_holds_no_names_or_emails(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Private Name")
    resp = client.put(
        f"{BASE}/{target_id}/roles/commercial",
        headers={**admin_headers, **_if_match(_row_version(sync_engine, target_id))},
    )
    assert resp.status_code == 200
    (event,) = _role_events(sync_engine, target_id)
    assert event["payload"] == {"role": "commercial"}
    assert "Private Name" not in str(event)
    assert "@" not in str(event["payload"])


def test_list_orders_by_name_case_insensitively_then_id(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    tag = uuid4().hex[:8]
    names = [f"zz{tag} bravo", f"ZZ{tag} Alpha", f"zz{tag} charlie", f"ZZ{tag} ALPHA"]
    ids = {name: str(_signed_in(client, name)[1]) for name in names}

    listed: list[dict[str, Any]] = []
    page = 1
    while True:
        body = client.get(
            BASE, headers=admin_headers, params={"page": page, "page_size": 200}
        ).json()
        listed.extend(u for u in body["items"] if u["id"] in ids.values())
        if page * 200 >= body["total"]:
            break
        page += 1

    alphas = sorted([ids[f"ZZ{tag} Alpha"], ids[f"ZZ{tag} ALPHA"]])  # same name: by id
    assert [u["id"] for u in listed] == [*alphas, ids[names[0]], ids[names[2]]]


def test_last_changed_by_is_the_latest_role_changer(
    client: TestClient, sync_engine: Engine
) -> None:
    a_headers, _ = _admin(client, sync_engine, "Admin First")
    b_headers, _ = _admin(client, sync_engine, "Admin Second")
    _, target_id = _signed_in(client, f"Changed {uuid4().hex[:8]}")
    version = _row_version(sync_engine, target_id)
    assert (
        client.put(
            f"{BASE}/{target_id}/roles/commercial", headers={**a_headers, **_if_match(version)}
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"{BASE}/{target_id}/roles/pm_reviewer",
            headers={**b_headers, **_if_match(version + 1)},
        ).status_code
        == 200
    )

    one = client.get(f"{BASE}/{target_id}", headers=a_headers).json()
    assert one["last_changed_by"] == "Admin Second"
    page = 1
    item = None
    while item is None:
        body = client.get(BASE, headers=a_headers, params={"page": page, "page_size": 200}).json()
        item = next((u for u in body["items"] if u["id"] == str(target_id)), None)
        assert body["items"], "target not listed"
        page += 1
    assert item["last_changed_by"] == "Admin Second"


def test_if_match_beyond_int4_is_412(client: TestClient, sync_engine: Engine) -> None:
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    for method in ("put", "delete"):
        resp = client.request(
            method,
            f"{BASE}/{target_id}/roles/commercial",
            headers={**admin_headers, "If-Match": f'"{2**31}"'},
        )
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")


def test_role_written_without_a_version_bump_is_412_and_rolls_back(
    client: TestClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grant that appears between the role read and the write (from a path that didn't
    bump the version) makes the caller's view stale: 412, and the bump is rolled back."""
    admin_headers, _ = _admin(client, sync_engine)
    _, target_id = _signed_in(client, "Target Person")
    version = _row_version(sync_engine, target_id)
    real_bump = repository.bump_row_version

    async def bump_then_sneak_in_grant(uow: Any, user_id: UUID, expected: int) -> int | None:
        new_version = await real_bump(uow, user_id, expected)
        _grant(sync_engine, user_id, "commercial")  # committed, without a version bump
        return new_version

    monkeypatch.setattr(repository, "bump_row_version", bump_then_sneak_in_grant)
    resp = client.put(
        f"{BASE}/{target_id}/roles/commercial", headers={**admin_headers, **_if_match(version)}
    )

    assert resp.status_code == 412, resp.text
    assert_problem(resp.json(), 412, "row_version_mismatch")
    assert _row_version(sync_engine, target_id) == version
    assert _role_events(sync_engine, target_id) == []
