"""User search for the collaborator picker (Story 1.7), against Postgres as psa_app."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.auth_tokens import auth_app
from tests.conftest import make_client
from tests.test_health import assert_problem
from tests.test_role_admin import _signed_in

SEARCH = "/api/v1/users/search"


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _ids(body: dict[str, list[dict[str, str]]]) -> list[str]:
    return [item["id"] for item in body["items"]]


def _searcher(client: TestClient, engine: Engine) -> dict[str, str]:
    headers, _ = _signed_in(client, "Searcher Person", "presales_engineer")
    return headers


def test_matches_name_or_email_of_any_provisioned_user(
    client: TestClient, sync_engine: Engine
) -> None:
    headers = _searcher(client, sync_engine)
    tag = uuid4().hex[:10]
    _, with_role = _signed_in(client, f"Findable {tag}", "commercial")
    _, without_role = _signed_in(client, f"Roleless {tag}")

    resp = client.get(SEARCH, headers=headers, params={"q": tag.upper()})

    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == [str(with_role), str(without_role)]  # by name
    item = resp.json()["items"][0]
    assert set(item) == {"id", "name", "email"}


def test_matches_email(client: TestClient, sync_engine: Engine) -> None:
    headers = _searcher(client, sync_engine)
    _, user_id = _signed_in(client, "Email Match", "pm_reviewer")
    email = client.get(SEARCH, headers=headers, params={"q": "Email Match", "limit": 50}).json()[
        "items"
    ]
    address = next(u["email"] for u in email if u["id"] == str(user_id))

    resp = client.get(SEARCH, headers=headers, params={"q": address.split("@")[0]})

    assert _ids(resp.json()) == [str(user_id)]


def test_like_wildcards_are_literal(client: TestClient, sync_engine: Engine) -> None:
    headers = _searcher(client, sync_engine)
    tag = uuid4().hex[:10]
    _, plain = _signed_in(client, f"Wild {tag} x", "commercial")
    for q in ("%%", "__", f"{tag}%x", "\\\\"):
        resp = client.get(SEARCH, headers=headers, params={"q": q})
        assert resp.status_code == 200
        assert str(plain) not in _ids(resp.json()), q


def test_limit_and_validation(client: TestClient, sync_engine: Engine) -> None:
    headers = _searcher(client, sync_engine)
    tag = uuid4().hex[:10]
    for i in range(3):
        _signed_in(client, f"Limited {tag} {i}")
    assert (
        len(client.get(SEARCH, headers=headers, params={"q": tag, "limit": 2}).json()["items"]) == 2
    )
    for params in (
        {},
        {"q": ""},
        {"q": "a"},  # one character is too short
        {"q": "x" * 101},
        {"q": "ab", "limit": 0},
        {"q": "ab", "limit": 51},
    ):
        resp = client.get(SEARCH, headers=headers, params=params)
        assert resp.status_code == 422, params
        assert_problem(resp.json(), 422, "validation_error")
    blank = client.get(SEARCH, headers=headers, params={"q": "   "})
    assert blank.status_code == 200
    assert blank.json()["items"] == []


def test_orders_by_name_case_insensitively_then_id(client: TestClient, sync_engine: Engine) -> None:
    headers = _searcher(client, sync_engine)
    tag = uuid4().hex[:10]
    names = [f"zz{tag} bravo", f"ZZ{tag} Alpha", f"zz{tag} charlie", f"ZZ{tag} ALPHA"]
    ids: dict[str, str] = {}
    for name in names:
        _, user_id = _signed_in(client, name)
        ids[name] = str(user_id)
    alphas = sorted([ids[f"ZZ{tag} Alpha"], ids[f"ZZ{tag} ALPHA"]])  # same name: by id
    expected = [*alphas, ids[names[0]], ids[names[2]]]

    full = client.get(SEARCH, headers=headers, params={"q": tag})
    limited = client.get(SEARCH, headers=headers, params={"q": tag, "limit": 3})

    assert _ids(full.json()) == expected
    assert _ids(limited.json()) == expected[:3]


@pytest.mark.parametrize("role", [None, "commercial", "head_of_delivery", "platform_administrator"])
def test_non_presales_engineers_are_forbidden(
    client: TestClient, sync_engine: Engine, role: str | None
) -> None:
    headers, _ = _signed_in(client, "Not An Engineer", *([role] if role else []))
    resp = client.get(SEARCH, headers=headers, params={"q": "ab"})
    assert resp.status_code == 403
    assert_problem(resp.json(), 403, "forbidden")


def test_unauthenticated_is_401(client: TestClient) -> None:
    resp = client.get(SEARCH, params={"q": "ab"})
    assert resp.status_code == 401
    assert_problem(resp.json(), 401, "token_missing")
