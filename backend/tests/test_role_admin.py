"""Users & roles (Story 1.6; read-only since Story 1.9) against a real, migrated Postgres as
psa_app.

Roles and permissions come from the access token (Auth0 RBAC). The page shows each user's
roles from a display-only cache refreshed from their token, so as of their last sign-in.
Covers: the cache refresh on sign-in, rewrite only on change, permission-based access (403
without `identity.user.list`, whatever the roles), no write endpoints, unknown user (404),
pagination and ordering.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.identity.adapters import repository
from tests.auth_tokens import (
    EMAIL_CLAIM,
    NAME_CLAIM,
    PERMISSIONS_CLAIM,
    ROLES_CLAIM,
    auth_app,
    bearer,
    claims,
    make_token,
    permissions_for,
)
from tests.conftest import make_client
from tests.test_health import assert_problem

ADMIN = "platform_administrator"
BASE = "/api/v1/admin/users"

_PROFILES: dict[UUID, tuple[str, str, str]] = {}
"""user id -> (sub, name, email), so a test can issue that user a new token."""


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _token(
    sub: str, name: str, email: str, roles: tuple[str, ...], permissions: list[str] | None
) -> dict[str, str]:
    token_claims = claims(
        sub,
        **{
            NAME_CLAIM: name,
            EMAIL_CLAIM: email,
            ROLES_CLAIM: list(roles),
            PERMISSIONS_CLAIM: permissions_for(roles) if permissions is None else permissions,
        },
    )
    return bearer(make_token(token_claims))


def _signed_in(
    client: TestClient, name: str, *roles: str, permissions: list[str] | None = None
) -> tuple[dict[str, str], UUID]:
    """Sign a fresh user in through `/me` with a token carrying `roles` and, unless given,
    the permissions Auth0 issues for them (README seed). Returns auth headers and id."""
    sub, email = f"auth0|{uuid4().hex}", f"{uuid4().hex}@ex.test"
    headers = _token(sub, name, email, roles, permissions)
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 200, resp.text
    user_id = UUID(resp.json()["id"])
    _PROFILES[user_id] = (sub, name, email)
    return headers, user_id


def _reissue(user_id: UUID, *roles: str, permissions: list[str] | None = None) -> dict[str, str]:
    """Headers with a new token for an existing user, as after a role change in Auth0."""
    sub, name, email = _PROFILES[user_id]
    return _token(sub, name, email, roles, permissions)


def _admin(client: TestClient, name: str = "Admin Person") -> tuple[dict[str, str], UUID]:
    return _signed_in(client, name, ADMIN)


def _cached(engine: Engine, user_id: UUID) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text("SELECT role FROM identity_user_roles WHERE user_id = :u ORDER BY role"),
                {"u": user_id},
            ).scalars()
        )


def _cache_xmins(engine: Engine, user_id: UUID) -> list[str]:
    """The cache rows' creating transaction ids: unchanged rows keep theirs."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT xmin::text FROM identity_user_roles WHERE user_id = :u ORDER BY role"),
            {"u": user_id},
        )
        return [str(value) for value in rows.scalars()]


def _role_events(engine: Engine, user_id: UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE subject_type = 'identity.user' "
                    "AND subject_id = :u AND event_type LIKE 'identity.user.role_%'"
                ),
                {"u": user_id},
            ).mappings()
        ]


# --- the cache: refreshed from the token at sign-in -----------------------------------------


def test_admin_with_no_cached_roles_signs_in_and_sees_own_roles(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, admin_id = _admin(client)
    with sync_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM identity_user_roles WHERE user_id = :u"), {"u": admin_id})

    resp = client.get(f"{BASE}/{admin_id}", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["roles"] == [ADMIN]
    assert _cached(sync_engine, admin_id) == [ADMIN]


def test_roles_are_shown_as_of_last_sign_in_with_no_edit_endpoints(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, _ = _admin(client)
    _, b_id = _signed_in(client, "User B", "commercial")

    resp = client.get(f"{BASE}/{b_id}", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["roles"] == ["commercial"]
    assert set(body) == {"id", "name", "email", "roles", "row_version"}
    for method in ("put", "delete"):
        write = client.request(
            method, f"{BASE}/{b_id}/roles/pm_reviewer", headers={**admin_headers, "If-Match": '"1"'}
        )
        assert write.status_code in (404, 405), write.text
    assert _cached(sync_engine, b_id) == ["commercial"]


def test_role_change_in_auth0_shows_after_the_users_next_token(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, _ = _admin(client)
    _, b_id = _signed_in(client, "User B", "commercial")
    version = client.get(f"{BASE}/{b_id}", headers=admin_headers).json()["row_version"]

    new_headers = _reissue(b_id, "pm_reviewer", "commercial")
    # Until B's next token reaches the API, the page still shows the old roles.
    assert client.get(f"{BASE}/{b_id}", headers=admin_headers).json()["roles"] == ["commercial"]

    me = client.get("/api/v1/me", headers=new_headers)
    assert me.json()["roles"] == ["commercial", "pm_reviewer"]
    after = client.get(f"{BASE}/{b_id}", headers=admin_headers).json()
    assert after["roles"] == ["commercial", "pm_reviewer"]
    assert after["row_version"] == version  # the cache is not a versioned write
    assert _role_events(sync_engine, b_id) == []  # and appends no trace event

    client.get("/api/v1/me", headers=_reissue(b_id))
    assert client.get(f"{BASE}/{b_id}", headers=admin_headers).json()["roles"] == []
    assert _cached(sync_engine, b_id) == []


def test_cache_is_rewritten_only_when_the_tokens_roles_differ(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, user_id = _signed_in(client, "Stable Roles", "commercial", "pm_reviewer")
    before = _cache_xmins(sync_engine, user_id)
    assert len(before) == 2

    for _ in range(2):
        assert client.get("/api/v1/me", headers=headers).status_code == 200

    assert _cache_xmins(sync_engine, user_id) == before


def test_unknown_roles_are_not_cached_and_cached_unknowns_are_hidden(
    client: TestClient, sync_engine: Engine
) -> None:
    admin_headers, _ = _admin(client)
    _, user_id = _signed_in(client, "Intern Person", "intern", "commercial")
    assert _cached(sync_engine, user_id) == ["commercial"]
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO identity_user_roles (user_id, role) VALUES (:u, 'retired_role')"),
            {"u": user_id},
        )

    resp = client.get(f"{BASE}/{user_id}", headers=admin_headers)

    assert resp.json()["roles"] == ["commercial"]


# --- authorization: permissions from the token, never the cache ------------------------------


@pytest.mark.parametrize(
    ("roles", "permissions"),
    [
        (("presales_engineer",), None),
        ((ADMIN,), []),  # the role without its Auth0 permission
        ((), ["identity.user.search"]),
    ],
)
def test_without_user_list_permission_is_403(
    client: TestClient, roles: tuple[str, ...], permissions: list[str] | None
) -> None:
    headers, user_id = _signed_in(client, "No List", *roles, permissions=permissions)
    for resp in (
        client.get(BASE, headers=headers),
        client.get(f"{BASE}/{user_id}", headers=headers),
    ):
        assert resp.status_code == 403, resp.text
        assert_problem(resp.json(), 403, "forbidden")


def test_user_list_permission_alone_is_enough(client: TestClient) -> None:
    headers, user_id = _signed_in(client, "Lister", permissions=["identity.user.list"])
    assert client.get(BASE, headers=headers).status_code == 200
    assert client.get(f"{BASE}/{user_id}", headers=headers).json()["roles"] == []


def test_authorization_ignores_the_cache(
    client: TestClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache that claims `platform_administrator` grants nothing: only the token counts."""
    headers, _ = _signed_in(client, "Cached Admin")

    async def cache_says_admin(uow: Any, user_id: UUID) -> list[str]:
        return [ADMIN]

    async def keep_cache(uow: Any, user_id: UUID, roles: list[str]) -> None:
        return None

    monkeypatch.setattr(repository, "load_roles", cache_says_admin)
    monkeypatch.setattr(repository, "replace_roles", keep_cache)

    assert client.get(BASE, headers=headers).status_code == 403
    assert client.get("/api/v1/me", headers=headers).json()["roles"] == []


def test_unauthenticated_is_401(client: TestClient) -> None:
    resp = client.get(BASE)
    assert resp.status_code == 401
    assert_problem(resp.json(), 401, "token_missing")


def test_unknown_user_is_404(client: TestClient) -> None:
    admin_headers, _ = _admin(client)
    resp = client.get(f"{BASE}/{uuid4()}", headers=admin_headers)
    assert resp.status_code == 404
    assert_problem(resp.json(), 404, "not_found")


# --- reads ----------------------------------------------------------------------------------


def test_get_user_returns_etag(client: TestClient) -> None:
    admin_headers, _ = _admin(client)
    _, target_id = _signed_in(client, "Target Person", "pm_reviewer", "commercial")

    resp = client.get(f"{BASE}/{target_id}", headers=admin_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Target Person"
    assert body["roles"] == ["commercial", "pm_reviewer"]
    assert resp.headers["ETag"] == f'"{body["row_version"]}"'


def test_list_is_paginated_with_roles(client: TestClient) -> None:
    admin_headers, admin_id = _admin(client)
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
    assert client.get(f"{BASE}/{admin_id}", headers=admin_headers).json()["roles"] == [ADMIN]

    for params in (
        {"page": 0},
        {"page": 1_000_001},
        {"page": 2**63},
        {"page_size": 0},
        {"page_size": 201},
    ):
        bad = client.get(BASE, headers=admin_headers, params=params)
        assert bad.status_code == 422, params


def test_list_orders_by_name_case_insensitively_then_id(client: TestClient) -> None:
    admin_headers, _ = _admin(client)
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
