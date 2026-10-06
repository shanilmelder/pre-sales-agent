"""The Integration Type and Work Package catalogue (Story 3.1) against a real, migrated
Postgres as psa_app: the spec's I/O matrix, 403/412/428, retired resolution and the trace."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.knowledge.application import public as knowledge
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_role_admin import _admin, _grant, _signed_in

BASE = "/api/v1/catalogue/entries"
CODES = {
    403: "forbidden",
    404: "not_found",
    409: "catalogue_duplicate",
    412: "row_version_mismatch",
    422: "validation_error",
    428: "if_match_required",
}


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _problem(resp: Response, status: int) -> None:
    assert resp.status_code == status, resp.text
    assert_problem(resp.json(), status, CODES[status])


def _if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def _body(**overrides: Any) -> dict[str, Any]:
    body = {
        "kind": "integration_type",
        "code": f"C-{uuid4().hex[:8]}",
        "name": f"Name {uuid4().hex}",
        "definition": "Exchange of documents.",
    }
    return {**body, **overrides}


def _create(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    resp = client.post(BASE, headers=headers, json=_body(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _events(engine: Engine, entry_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT event_type, opportunity_id, payload FROM platform_trace_events "
                "WHERE subject_id = :s ORDER BY id"
            ),
            {"s": entry_id},
        ).mappings()
        return [dict(r) for r in rows]


def test_create_is_version_one_with_one_event(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    resp = client.post(BASE, headers=admin, json=_body(name="  Padded  ", code=" PAD "))
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert (entry["version"], entry["current_version"], entry["row_version"]) == (1, 1, 1)
    assert (entry["name"], entry["code"], entry["status"], entry["retired"]) == (
        "Padded",
        "PAD",
        "active",
        False,
    )
    assert resp.headers["ETag"] == '"1"'
    (event,) = _events(sync_engine, entry["id"])
    assert event["event_type"] == "knowledge.catalogue_entry.created"
    assert event["opportunity_id"] is None
    assert event["payload"] == {"kind": "integration_type", "version": 1}


def test_duplicate_name_or_code_is_409_and_saves_nothing(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client, sync_engine)
    first = _create(client, admin)
    for field, body in (
        ("name", _body(name=first["name"].upper())),
        ("code", _body(code=first["code"].lower())),
    ):
        resp = client.post(BASE, headers=admin, json=body)
        _problem(resp, 409)
        assert (
            resp.json()["detail"] == f"An active Integration Type with this {field} already exists"
        )
    other_kind = client.post(
        BASE, headers=admin, json=_body(kind="work_package", name=first["name"])
    )
    assert other_kind.status_code == 201  # the same name under the other kind is fine
    dup = client.post(BASE, headers=admin, json=_body(kind="work_package", name=first["name"]))
    assert dup.json()["detail"] == "An active Work Package with this name already exists"


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": " "},
        {"name": ""},
        {"definition": "  "},
        {"code": "x" * 41},
        {"name": "x" * 121},
        {"definition": "x" * 2001},
        {"kind": "other"},
        {"name": "bad\x00name"},
    ],
)
def test_invalid_fields_are_422(
    client: TestClient, sync_engine: Engine, overrides: dict[str, Any]
) -> None:
    admin, _ = _admin(client, sync_engine)
    _problem(client.post(BASE, headers=admin, json=_body(**overrides)), 422)


def test_edit_saves_a_new_version_and_keeps_the_old_readable(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client, sync_engine, "Edit Admin")
    entry = _create(client, admin, definition="First")
    url = f"{BASE}/{entry['id']}"
    resp = client.patch(url, headers={**admin, **_if_match(1)}, json={"definition": "Second"})
    assert resp.status_code == 200, resp.text
    edited = resp.json()
    assert (edited["version"], edited["row_version"], edited["definition"]) == (2, 2, "Second")
    assert resp.headers["ETag"] == '"2"'
    old = client.get(url, headers=admin, params={"version": 1}).json()
    assert (old["definition"], old["version"], old["current_version"]) == ("First", 1, 2)
    versions = client.get(f"{url}/versions", headers=admin).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["changed_by_name"] == "Edit Admin"
    assert client.get(url, headers=admin, params={"version": 3}).status_code == 404
    updated = _events(sync_engine, entry["id"])[-1]
    assert updated["event_type"] == "knowledge.catalogue_entry.updated"
    assert updated["payload"] == {"kind": "integration_type", "from_version": 1, "to_version": 2}


def test_unchanged_edit_is_a_200_no_op(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    resp = client.patch(
        f"{BASE}/{entry['id']}",
        headers={**admin, **_if_match(1)},
        json={"name": f" {entry['name']} ", "definition": entry["definition"]},
    )
    assert resp.status_code == 200
    assert (resp.json()["version"], resp.json()["row_version"]) == (1, 1)
    assert len(_events(sync_engine, entry["id"])) == 1


def test_stale_and_missing_if_match(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    url = f"{BASE}/{entry['id']}"
    client.patch(url, headers={**admin, **_if_match(1)}, json={"name": f"New {uuid4().hex}"})
    stale = client.patch(url, headers={**admin, **_if_match(1)}, json={"definition": "Lost"})
    _problem(stale, 412)
    _problem(client.patch(url, headers=admin, json={"definition": "x"}), 428)
    _problem(client.post(f"{url}/retire", headers=admin, json={"reason": "r"}), 428)
    _problem(client.post(f"{url}/reactivate", headers=admin), 428)
    assert client.get(url, headers=admin).json()["definition"] == entry["definition"]


def test_edit_to_an_active_name_is_409(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    a, b = _create(client, admin), _create(client, admin)
    resp = client.patch(
        f"{BASE}/{b['id']}", headers={**admin, **_if_match(1)}, json={"name": a["name"].lower()}
    )
    _problem(resp, 409)


def test_retire_resolves_but_does_not_validate_then_reactivate(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    url = f"{BASE}/{entry['id']}"
    blank = client.post(f"{url}/retire", headers={**admin, **_if_match(1)}, json={"reason": "  "})
    _problem(blank, 422)
    resp = client.post(
        f"{url}/retire", headers={**admin, **_if_match(1)}, json={"reason": "Superseded"}
    )
    assert resp.status_code == 200, resp.text
    retired = resp.json()
    assert (retired["status"], retired["retired"], retired["retired_reason"]) == (
        "retired",
        True,
        "Superseded",
    )
    assert retired["row_version"] == 2

    async def check() -> tuple[bool, Any]:
        engine = create_async_engine(db_url)
        try:
            async with unit_of_work(engine) as uow:
                found = await knowledge.get_catalogue_entry(uow, UUID(entry["id"]))
                return await knowledge.validate_catalogue_ref(uow, UUID(entry["id"])), found
        finally:
            await engine.dispose()

    valid, found = run_async(check())
    assert valid is False
    assert found is not None
    assert found.retired is True
    assert found.name == entry["name"]

    listed = client.get(BASE, headers=admin).json()["items"]
    assert entry["id"] not in {e["id"] for e in listed}
    everything = client.get(BASE, headers=admin, params={"include_retired": "true"}).json()
    assert entry["id"] in {e["id"] for e in everything["items"]}

    back = client.post(f"{url}/reactivate", headers={**admin, **_if_match(2)})
    assert back.status_code == 200, back.text
    assert (back.json()["status"], back.json()["retired_reason"]) == ("active", None)
    kinds = [e["event_type"] for e in _events(sync_engine, entry["id"])]
    assert kinds == [
        "knowledge.catalogue_entry.created",
        "knowledge.catalogue_entry.retired",
        "knowledge.catalogue_entry.reactivated",
    ]


def test_reactivate_is_409_when_an_active_entry_took_the_name(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    url = f"{BASE}/{entry['id']}"
    client.post(f"{url}/retire", headers={**admin, **_if_match(1)}, json={"reason": "Old"})
    _create(client, admin, name=entry["name"])  # retired entries don't block the name
    resp = client.post(f"{url}/reactivate", headers={**admin, **_if_match(2)})
    _problem(resp, 409)
    assert client.get(url, headers=admin).json()["status"] == "retired"


def test_non_admin_writes_are_403_but_any_role_reads(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    url = f"{BASE}/{entry['id']}"
    reader, reader_id = _signed_in(client, "Reader")
    _problem(client.get(BASE, headers=reader), 403)  # no role yet
    _grant(sync_engine, reader_id, "sales_representative")
    assert client.get(BASE, headers=reader).status_code == 200
    assert client.get(url, headers=reader).status_code == 200
    assert client.get(f"{url}/versions", headers=reader).status_code == 200
    _problem(client.post(BASE, headers=reader, json=_body()), 403)
    writes = [
        client.patch(url, headers={**reader, **_if_match(1)}, json={"definition": "x"}),
        client.post(f"{url}/retire", headers={**reader, **_if_match(1)}, json={"reason": "r"}),
        client.post(f"{url}/reactivate", headers={**reader, **_if_match(1)}),
    ]
    for resp in writes:
        _problem(resp, 403)
    assert client.get(url, headers=admin).json()["row_version"] == 1


def test_unknown_entry_is_404(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    _problem(client.get(f"{BASE}/{uuid4()}", headers=admin), 404)
    patched = client.patch(
        f"{BASE}/{uuid4()}", headers={**admin, **_if_match(1)}, json={"name": "x"}
    )
    _problem(patched, 404)


def test_trace_never_carries_text(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin, name="Secret name", definition="Secret definition")
    url = f"{BASE}/{entry['id']}"
    client.patch(url, headers={**admin, **_if_match(1)}, json={"definition": "Secret two"})
    client.post(f"{url}/retire", headers={**admin, **_if_match(2)}, json={"reason": "Secret why"})
    dumped = str(_events(sync_engine, entry["id"]))
    assert "Secret" not in dumped
    assert entry["code"] not in dumped


def test_psa_app_cannot_change_or_delete_versions(sync_engine: Engine) -> None:
    for sql in (
        "UPDATE knowledge_catalogue_entry_versions SET name = 'x'",
        "DELETE FROM knowledge_catalogue_entry_versions",
        "DELETE FROM knowledge_catalogue_entries",
    ):
        with sync_engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError):
            conn.execute(sa.text(sql))


def test_rename_to_own_name_in_other_case_is_allowed(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    resp = client.patch(
        f"{BASE}/{entry['id']}",
        headers={**admin, **_if_match(1)},
        json={"name": entry["name"].upper()},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_version"] == 2


def test_repeated_retire_and_reactivate_are_no_ops_and_stale_still_412(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    url = f"{BASE}/{entry['id']}"
    again = client.post(f"{url}/reactivate", headers={**admin, **_if_match(1)})
    assert again.status_code == 200 and again.json()["row_version"] == 1
    first = client.post(
        f"{url}/retire", headers={**admin, **_if_match(1)}, json={"reason": "Superseded"}
    )
    assert first.status_code == 200
    second = client.post(
        f"{url}/retire", headers={**admin, **_if_match(2)}, json={"reason": "Other reason"}
    )
    assert second.status_code == 200
    assert (second.json()["row_version"], second.json()["retired_reason"]) == (2, "Superseded")
    stale = client.patch(url, headers={**admin, **_if_match(1)}, json={"name": entry["name"]})
    _problem(stale, 412)
    huge = client.patch(
        url, headers={**admin, **_if_match(2**31 - 1)}, json={"name": entry["name"]}
    )
    _problem(huge, 412)
    kinds = [e["event_type"] for e in _events(sync_engine, entry["id"])]
    assert kinds == ["knowledge.catalogue_entry.created", "knowledge.catalogue_entry.retired"]


def test_version_query_is_bounded(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client, sync_engine)
    entry = _create(client, admin)
    for bad in ("0", "99999999999"):
        _problem(client.get(f"{BASE}/{entry['id']}", headers=admin, params={"version": bad}), 422)
