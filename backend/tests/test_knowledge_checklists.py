"""Checklists (Story 3.4) against a real, migrated Postgres as psa_app: the spec's I/O
matrix (create, save draft, publish, edit published, retire, find applicable), 403 per role,
412/428, stable item ids across versions, the published version staying in use until the
draft is published, insert-only versions and items, and the trace."""

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
from app.modules.knowledge.application.public import ApplicableChecklist
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_role_admin import _admin, _reissue, _signed_in

BASE = "/api/v1/knowledge/checklists"
CATALOGUE = "/api/v1/catalogue/entries"
CODES = {
    403: "forbidden",
    404: "not_found",
    409: "knowledge_checklist_retired",
    412: "row_version_mismatch",
    422: "validation_error",
    428: "if_match_required",
}
WRITERS = ("engineering_reviewer", "pm_reviewer", "security_reviewer", "platform_administrator")
READERS = (
    "presales_engineer",
    "sales_representative",
    "commercial",
    "delivery_manager",
    "head_of_delivery",
)


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _problem(resp: Response, status: int, code: str | None = None) -> None:
    assert resp.status_code == status, resp.text
    assert_problem(resp.json(), status, code or CODES[status])


def _if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def _author(client: TestClient, role: str = "security_reviewer") -> dict[str, str]:
    headers, _ = _signed_in(client, f"Author {uuid4().hex[:6]}", role)
    return headers


def _entry(client: TestClient, admin: dict[str, str], kind: str = "integration_type") -> str:
    resp = client.post(
        CATALOGUE,
        headers=admin,
        json={
            "kind": kind,
            "code": f"C-{uuid4().hex[:8]}",
            "name": f"Entry {uuid4().hex}",
            "definition": "A definition.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]  # type: ignore[no-any-return]


def _retire_entry(client: TestClient, admin: dict[str, str], entry_id: str) -> None:
    resp = client.post(
        f"{CATALOGUE}/{entry_id}/retire", headers={**admin, **_if_match(1)}, json={"reason": "Old"}
    )
    assert resp.status_code == 200, resp.text


def _create(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    resp = client.post(
        BASE, headers=headers, json={"name": f"List {uuid4().hex}", "domain": "security", **body}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _item(**over: Any) -> dict[str, Any]:
    return {
        "id": None,
        "kind": "question",
        "text": "Is SSO required?",
        "why_it_matters": "SSO changes the identity design.",
        "affected_entry_id": None,
        "impact": "high",
        "mandatory": False,
        **over,
    }


def _draft(checklist: dict[str, Any], **over: Any) -> dict[str, Any]:
    draft = checklist["draft"]
    body = {
        "name": draft["name"],
        "domain": draft["domain"],
        "products": draft["products"],
        "industry": draft["industry"],
        "integration_type_ids": [t["id"] for t in draft["integration_types"]],
        "items": [
            {
                "id": i["id"],
                "kind": i["kind"],
                "text": i["text"],
                "why_it_matters": i["why_it_matters"],
                "affected_entry_id": None
                if i["affected_area"] is None
                else i["affected_area"]["id"],
                "impact": i["impact"],
                "mandatory": i["mandatory"],
            }
            for i in draft["items"]
        ],
    }
    return {**body, **over}


def _save(
    client: TestClient, headers: dict[str, str], checklist: dict[str, Any], **over: Any
) -> Response:
    return client.put(
        f"{BASE}/{checklist['id']}/draft",
        headers={**headers, **_if_match(checklist["row_version"])},
        json=_draft(checklist, **over),
    )


def _saved(
    client: TestClient, headers: dict[str, str], checklist: dict[str, Any], **over: Any
) -> dict[str, Any]:
    resp = _save(client, headers, checklist, **over)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _publish(client: TestClient, headers: dict[str, str], checklist: dict[str, Any]) -> Response:
    return client.post(
        f"{BASE}/{checklist['id']}/publish",
        headers={**headers, **_if_match(checklist["row_version"])},
    )


def _published(
    client: TestClient, headers: dict[str, str], checklist: dict[str, Any]
) -> dict[str, Any]:
    resp = _publish(client, headers, checklist)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _events(engine: Engine, checklist_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT event_type, opportunity_id, subject_type, payload "
                "FROM platform_trace_events WHERE subject_id = :s ORDER BY id"
            ),
            {"s": checklist_id},
        ).mappings()
        return [dict(r) for r in rows]


def _applicable(
    db_url: str,
    *,
    products: list[str] | None = None,
    industry: str | None = None,
    types: list[str] | None = None,
) -> list[ApplicableChecklist]:
    async def go() -> list[ApplicableChecklist]:
        engine = create_async_engine(db_url)
        try:
            async with unit_of_work(engine) as uow:
                return await knowledge.find_applicable_checklists(
                    uow,
                    products=products or [],
                    industry=industry,
                    integration_type_ids=[UUID(t) for t in types or []],
                )
        finally:
            await engine.dispose()

    return run_async(go())


def _ready(client: TestClient, author: dict[str, str], **draft: Any) -> dict[str, Any]:
    """A Checklist with a publishable draft."""
    checklist = _create(client, author)
    return _saved(
        client,
        author,
        checklist,
        **{"products": [f"Product {uuid4().hex}"], "items": [_item()], **draft},
    )


# --- create ---------------------------------------------------------------------------------


def test_create_is_a_draft_with_no_version(client: TestClient, sync_engine: Engine) -> None:
    author = _author(client)
    resp = client.post(
        BASE, headers=author, json={"name": "  Security baseline ", "domain": "security"}
    )
    assert resp.status_code == 201, resp.text
    checklist = resp.json()
    assert resp.headers["ETag"] == '"1"'
    assert (checklist["row_version"], checklist["current_version"]) == (1, None)
    assert (checklist["name"], checklist["domain"], checklist["status"]) == (
        "Security baseline",
        "security",
        "active",
    )
    assert checklist["items"] == [] and checklist["item_count"] == 0
    draft = checklist["draft"]
    assert draft["name"] == "Security baseline" and draft["items"] == []
    assert draft["publishable"] is False
    assert _events(sync_engine, checklist["id"]) == []


@pytest.mark.parametrize(
    "body",
    [
        {"name": " ", "domain": "security"},
        {"name": "x" * 201, "domain": "security"},
        {"name": "Fine", "domain": "legal"},
        {"name": "Fine"},
    ],
)
def test_create_rejects_a_bad_name_or_domain(client: TestClient, body: dict[str, Any]) -> None:
    _problem(client.post(BASE, headers=_author(client), json=body), 422)


@pytest.mark.parametrize("role", WRITERS)
def test_every_writer_role_may_create(client: TestClient, role: str) -> None:
    _create(client, _author(client, role))


# --- save draft -----------------------------------------------------------------------------


def test_save_replaces_the_draft_and_gives_new_items_ids(client: TestClient) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    type_id = _entry(client, admin)
    package = _entry(client, admin, "work_package")
    checklist = _create(client, author)
    saved = _saved(
        client,
        author,
        checklist,
        products=[" AutoStore ", "autostore", "SAP"],
        industry="  Retail ",
        integration_type_ids=[type_id],
        items=[_item(), _item(kind="risk", affected_entry_id=package, mandatory=True, text="")],
    )
    assert saved["row_version"] == 2
    draft = saved["draft"]
    assert draft["products"] == ["AutoStore", "SAP"]
    assert draft["industry"] == "Retail"
    assert [t["id"] for t in draft["integration_types"]] == [type_id]
    first, second = draft["items"]
    assert UUID(first["id"]).version == 7 and UUID(second["id"]).version == 7
    assert second["affected_area"]["kind"] == "work_package"
    assert second["mandatory"] is True
    assert draft["publishable"] is False  # the second item has no text yet
    # Saving again keeps the ids.
    again = _saved(client, author, saved, name="Renamed")
    assert [i["id"] for i in again["draft"]["items"]] == [first["id"], second["id"]]
    assert again["draft"]["name"] == "Renamed"
    assert again["name"] == checklist["name"]  # the header changes only on Publish


def test_stale_and_missing_if_match_overwrite_nothing(client: TestClient) -> None:
    author = _author(client)
    checklist = _create(client, author)
    other = _author(client, "pm_reviewer")
    _saved(client, other, checklist, name="Their name")
    stale = _save(client, author, checklist, name="My name")
    _problem(stale, 412)
    assert "changed by someone else" in stale.json()["detail"]
    url = f"{BASE}/{checklist['id']}"
    _problem(client.put(f"{url}/draft", headers=author, json=_draft(checklist)), 428)
    _problem(client.post(f"{url}/publish", headers=author), 428)
    _problem(client.post(f"{url}/draft", headers=author), 428)
    _problem(client.post(f"{url}/retire", headers=author, json={"reason": "r"}), 428)
    current = client.get(url, headers=author).json()
    assert current["draft"]["name"] == "Their name" and current["row_version"] == 2


def test_retired_or_wrong_kind_tags_and_areas_are_422(client: TestClient) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    retired_type = _entry(client, admin)
    _retire_entry(client, admin, retired_type)
    package = _entry(client, admin, "work_package")
    retired_package = _entry(client, admin, "work_package")
    _retire_entry(client, admin, retired_package)
    checklist = _create(client, author)
    for over in (
        {"integration_type_ids": [retired_type]},
        {"integration_type_ids": [package]},  # scope takes Integration Types only
        {"integration_type_ids": [str(uuid4())]},
        {"integration_type_ids": ["not-a-uuid"]},
        {"items": [_item(affected_entry_id=retired_package)]},
        {"items": [_item(affected_entry_id=str(uuid4()))]},
        {"items": [_item(id=str(uuid4()))]},  # an id that isn't this Checklist's
        {"products": ["  "]},
        {"name": ""},
    ):
        _problem(_save(client, author, checklist, **over), 422)
    assert client.get(f"{BASE}/{checklist['id']}", headers=author).json()["row_version"] == 1


def test_existing_references_keep_resolving_once_retired(client: TestClient) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    type_id = _entry(client, admin)
    package = _entry(client, admin, "work_package")
    checklist = _saved(
        client,
        author,
        _create(client, author),
        integration_type_ids=[type_id],
        items=[_item(affected_entry_id=package)],
    )
    _retire_entry(client, admin, type_id)
    _retire_entry(client, admin, package)
    shown = client.get(f"{BASE}/{checklist['id']}", headers=author).json()["draft"]
    assert shown["integration_types"][0]["retired"] is True
    assert shown["items"][0]["affected_area"]["retired"] is True
    # Saving the draft again with the same references is fine; they were already chosen.
    resaved = _saved(client, author, checklist, name="Still fine")
    published = _published(client, author, resaved)
    assert published["integration_types"][0]["retired"] is True
    assert published["items"][0]["affected_area"]["id"] == package


# --- publish --------------------------------------------------------------------------------


def test_publish_needs_a_scope_tag_and_an_item(client: TestClient) -> None:
    author = _author(client)
    checklist = _create(client, author)
    resp = _publish(client, author, checklist)
    _problem(resp, 422)
    assert "needs a scope tag and an item" in resp.json()["detail"]
    no_items = _saved(client, author, checklist, products=["P"])
    _problem(_publish(client, author, no_items), 422)
    blank = _saved(client, author, no_items, items=[_item(why_it_matters=" ")])
    assert blank["draft"]["publishable"] is False
    _problem(_publish(client, author, blank), 422)
    assert client.get(f"{BASE}/{checklist['id']}", headers=author).json()["current_version"] is None


def test_publish_makes_version_one_and_clears_the_draft(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    type_id = _entry(client, admin)
    # A unique industry: an active Checklist scoped to the industry every test Opportunity
    # uses ("Retail") would raise mandatory Gaps in other suites (Story 4.2).
    industry = f"Retail {uuid4().hex[:8]}"
    checklist = _ready(
        client,
        author,
        name="Published name",
        industry=industry,
        integration_type_ids=[type_id],
        items=[_item(mandatory=True), _item(kind="risk", text="Old firmware", impact="low")],
    )
    assert checklist["draft"]["publishable"] is True
    published = _published(client, author, checklist)
    assert published["current_version"] == 1
    assert published["draft"] is None
    assert published["name"] == "Published name"
    assert published["industry"] == industry
    assert [t["id"] for t in published["integration_types"]] == [type_id]
    assert (published["item_count"], published["mandatory_count"]) == (2, 1)
    assert [i["text"] for i in published["items"]] == ["Is SSO required?", "Old firmware"]
    (event,) = _events(sync_engine, checklist["id"])
    assert event["event_type"] == "knowledge.checklist.published"
    assert event["opportunity_id"] is None
    assert event["subject_type"] == "knowledge.checklist"
    assert event["payload"] == {"version": 1, "item_count": 2, "mandatory_count": 1}
    # Nothing left to publish or save.
    _problem(_publish(client, author, published), 409, "checklist_no_draft")
    _problem(
        _save(client, author, {**published, "draft": checklist["draft"]}), 409, "checklist_no_draft"
    )


# --- edit published -------------------------------------------------------------------------


def test_edit_published_keeps_item_ids_and_v1_applies_until_v2(
    client: TestClient, db_url: str
) -> None:
    author = _author(client)
    product = f"Product {uuid4().hex}"
    v1 = _published(
        client,
        author,
        _ready(client, author, products=[product], items=[_item(text="Keep"), _item(text="Drop")]),
    )
    keep, drop = v1["items"]
    url = f"{BASE}/{v1['id']}"

    opened = client.post(f"{url}/draft", headers={**author, **_if_match(v1["row_version"])})
    assert opened.status_code == 200, opened.text
    draft = opened.json()
    assert [i["id"] for i in draft["draft"]["items"]] == [keep["id"], drop["id"]]
    again = client.post(f"{url}/draft", headers={**author, **_if_match(draft["row_version"])})
    _problem(again, 409, "checklist_draft_exists")

    body = _draft(draft)
    body["items"] = [{**body["items"][0], "text": "Keep, reworded"}, _item(text="New")]
    edited = client.put(
        f"{url}/draft", headers={**author, **_if_match(draft["row_version"])}, json=body
    )
    assert edited.status_code == 200, edited.text
    edited_checklist = edited.json()

    # The published version stays in use until the draft is published.
    (found,) = [c for c in _applicable(db_url, products=[product]) if c.checklist_id == v1["id"]]
    assert found.version == 1
    assert [(i.item_id, i.text) for i in found.items] == [
        (keep["id"], "Keep"),
        (drop["id"], "Drop"),
    ]
    assert client.get(url, headers=author).json()["current_version"] == 1

    v2 = _published(client, author, edited_checklist)
    assert v2["current_version"] == 2
    (found,) = [c for c in _applicable(db_url, products=[product]) if c.checklist_id == v1["id"]]
    assert found.version == 2
    assert found.items[0].item_id == keep["id"]
    assert found.items[0].text == "Keep, reworded"
    assert drop["id"] not in {i.item_id for i in found.items}
    assert found.items[1].item_id not in {keep["id"], drop["id"]}

    # Version history: each version with its publisher and date; v1 stays readable.
    versions = client.get(f"{url}/versions", headers=author).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["published_by"]["name"].startswith("Author")
    assert versions[0]["published_at"]
    assert (versions[1]["item_count"], versions[1]["mandatory_count"]) == (2, 0)
    old = client.get(f"{url}/versions/1", headers=author).json()
    assert [i["text"] for i in old["items"]] == ["Keep", "Drop"]
    assert old["products"] == [product]
    _problem(client.get(f"{url}/versions/3", headers=author), 404)
    _problem(client.get(f"{url}/versions/0", headers=author), 422)


def test_an_item_dropped_then_restored_keeps_its_id(client: TestClient) -> None:
    author = _author(client)
    v1 = _published(
        client, author, _ready(client, author, items=[_item(text="A"), _item(text="B")])
    )
    a, b = v1["items"]
    url = f"{BASE}/{v1['id']}"
    draft = client.post(f"{url}/draft", headers={**author, **_if_match(v1["row_version"])}).json()
    without_b = _saved(client, author, draft, items=[_draft(draft)["items"][0]])
    restored = _saved(
        client,
        author,
        without_b,
        items=[*_draft(without_b)["items"], _item(id=b["id"], text="B")],
    )
    assert [i["id"] for i in restored["draft"]["items"]] == [a["id"], b["id"]]


# --- retire ---------------------------------------------------------------------------------


def test_retire_clears_the_draft_and_keeps_versions_readable(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    author = _author(client)
    product = f"Product {uuid4().hex}"
    v1 = _published(client, author, _ready(client, author, products=[product]))
    url = f"{BASE}/{v1['id']}"
    draft = client.post(f"{url}/draft", headers={**author, **_if_match(v1["row_version"])}).json()
    for bad in (" ", "x" * 501):
        resp = client.post(
            f"{url}/retire",
            headers={**author, **_if_match(draft["row_version"])},
            json={"reason": bad},
        )
        _problem(resp, 422)
    resp = client.post(
        f"{url}/retire",
        headers={**author, **_if_match(draft["row_version"])},
        json={"reason": "Secret why"},
    )
    assert resp.status_code == 200, resp.text
    retired = resp.json()
    assert (retired["status"], retired["retired"], retired["retired_reason"]) == (
        "retired",
        True,
        "Secret why",
    )
    assert retired["draft"] is None
    assert client.get(f"{url}/versions/1", headers=author).status_code == 200
    again = client.post(
        f"{url}/retire",
        headers={**author, **_if_match(retired["row_version"])},
        json={"reason": "Again"},
    )
    _problem(again, 409)
    _problem(
        client.post(f"{url}/draft", headers={**author, **_if_match(retired["row_version"])}), 409
    )
    assert v1["id"] not in {c.checklist_id for c in _applicable(db_url, products=[product])}
    listed = client.get(BASE, headers=author).json()["items"]
    assert v1["id"] not in {c["id"] for c in listed}
    everything = client.get(BASE, headers=author, params={"include_retired": "true"}).json()
    assert v1["id"] in {c["id"] for c in everything["items"]}
    event = _events(sync_engine, v1["id"])[-1]
    assert event["event_type"] == "knowledge.checklist.retired"
    assert event["opportunity_id"] is None
    assert event["payload"] == {"version": 1, "discarded_draft": True}
    assert "Secret" not in str(_events(sync_engine, v1["id"]))


def test_republishing_with_another_integration_type_moves_the_scope(
    client: TestClient, db_url: str
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    type_a, type_b = _entry(client, admin), _entry(client, admin)
    industry = f"Industry {uuid4().hex}"
    v1 = _published(
        client,
        author,
        _ready(client, author, products=[], industry=industry, integration_type_ids=[type_a]),
    )
    url = f"{BASE}/{v1['id']}"
    opened = client.post(f"{url}/draft", headers={**author, **_if_match(v1["row_version"])})
    assert opened.status_code == 200, opened.text
    draft = opened.json()
    assert [t["id"] for t in draft["draft"]["integration_types"]] == [type_a]
    assert draft["draft"]["industry"] == industry
    saved = _saved(client, author, draft, integration_type_ids=[type_b])
    v2 = _published(client, author, saved)
    assert [t["id"] for t in v2["integration_types"]] == [type_b]
    assert v1["id"] not in {c.checklist_id for c in _applicable(db_url, types=[type_a])}
    assert v1["id"] in {c.checklist_id for c in _applicable(db_url, types=[type_b])}


def test_a_never_published_draft_can_be_retired(client: TestClient, sync_engine: Engine) -> None:
    author = _author(client)
    checklist = _create(client, author)
    resp = client.post(
        f"{BASE}/{checklist['id']}/retire",
        headers={**author, **_if_match(1)},
        json={"reason": "No"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"] is None
    retired = resp.json()
    match = _if_match(retired["row_version"])
    url = f"{BASE}/{checklist['id']}"
    _problem(client.put(f"{url}/draft", headers={**author, **match}, json=_draft(checklist)), 409)
    _problem(client.post(f"{url}/publish", headers={**author, **match}), 409)
    (event,) = _events(sync_engine, checklist["id"])
    assert event["payload"] == {"version": None, "discarded_draft": True}


# --- find applicable ------------------------------------------------------------------------


def test_find_applicable_matches_any_scope_ignoring_case_and_space(
    client: TestClient, db_url: str
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    type_id = _entry(client, admin)
    tag = uuid4().hex
    by_product = _published(client, author, _ready(client, author, products=[f"Prod {tag}"]))
    by_industry = _published(
        client, author, _ready(client, author, products=[], industry=f"Industry {tag}")
    )
    by_type = _published(
        client, author, _ready(client, author, products=[], integration_type_ids=[type_id])
    )
    _ready(client, author, products=[f"Prod {tag}"])  # never published: never applies

    def ids(**kwargs: Any) -> set[str]:
        return {c.checklist_id for c in _applicable(db_url, **kwargs)}

    assert ids(products=[f"  PROD {tag.upper()} "]) == {by_product["id"]}
    assert ids(industry=f" industry {tag}") == {by_industry["id"]}
    assert ids(types=[type_id]) == {by_type["id"]}
    assert ids(products=[f"prod {tag}"], industry=f"INDUSTRY {tag}", types=[type_id]) == {
        by_product["id"],
        by_industry["id"],
        by_type["id"],
    }
    assert (
        ids(products=["nothing"], industry="nothing")
        & {
            by_product["id"],
            by_industry["id"],
            by_type["id"],
        }
        == set()
    )
    (found,) = _applicable(db_url, types=[type_id])
    assert found.domain == "security"
    assert found.items[0].mandatory is False


# --- authorization and storage --------------------------------------------------------------


@pytest.mark.parametrize("role", READERS)
def test_other_roles_read_but_every_write_is_403(client: TestClient, role: str) -> None:
    author = _author(client)
    checklist = _published(client, author, _ready(client, author))
    url = f"{BASE}/{checklist['id']}"
    reader = _author(client, role)
    assert client.get(BASE, headers=reader).status_code == 200
    assert client.get(url, headers=reader).status_code == 200
    assert client.get(f"{url}/versions", headers=reader).status_code == 200
    assert client.get(f"{url}/versions/1", headers=reader).status_code == 200
    match = _if_match(checklist["row_version"])
    writes = [
        client.post(BASE, headers=reader, json={"name": "Mine", "domain": "general"}),
        client.post(f"{url}/draft", headers={**reader, **match}),
        client.put(
            f"{url}/draft", headers={**reader, **match}, json=_draft(_ready(client, author))
        ),
        client.post(f"{url}/publish", headers={**reader, **match}),
        client.post(f"{url}/retire", headers={**reader, **match}, json={"reason": "r"}),
    ]
    for resp in writes:
        _problem(resp, 403)
    assert client.get(url, headers=reader).json()["row_version"] == checklist["row_version"]


def test_no_role_cannot_read(client: TestClient) -> None:
    headers, user_id = _signed_in(client, "Nobody")
    _problem(client.get(BASE, headers=headers), 403)
    assert client.get(BASE, headers=_reissue(user_id, "commercial")).status_code == 200


def test_unknown_checklist_is_404(client: TestClient) -> None:
    author = _author(client)
    _problem(client.get(f"{BASE}/{uuid4()}", headers=author), 404)
    _problem(client.post(f"{BASE}/{uuid4()}/publish", headers={**author, **_if_match(1)}), 404)


def test_trace_never_carries_text(client: TestClient, sync_engine: Engine) -> None:
    author = _author(client)
    checklist = _ready(
        client,
        author,
        name="Secret name",
        products=["Secret product"],
        items=[_item(text="Secret text", why_it_matters="Secret why")],
    )
    published = _published(client, author, checklist)
    client.post(
        f"{BASE}/{checklist['id']}/retire",
        headers={**author, **_if_match(published["row_version"])},
        json={"reason": "Secret reason"},
    )
    assert "Secret" not in str(_events(sync_engine, checklist["id"]))


def test_psa_app_cannot_change_or_delete_versions_or_items(sync_engine: Engine) -> None:
    for sql in (
        "UPDATE knowledge_checklist_versions SET name = 'x'",
        "DELETE FROM knowledge_checklist_versions",
        "UPDATE knowledge_checklist_items SET text = 'x'",
        "DELETE FROM knowledge_checklist_items",
        "DELETE FROM knowledge_checklists",
        "UPDATE knowledge_checklist_scope_tags SET entry_id = entry_id",
    ):
        with sync_engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError):
            conn.execute(sa.text(sql))
