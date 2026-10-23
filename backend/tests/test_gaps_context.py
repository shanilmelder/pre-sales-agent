"""The Gaps tab context (Story 4.1): `GET …/opportunities/{id}/gaps/context` against a real,
migrated Postgres as psa_app. It composes the applicable Checklists (by products, industry
and the tags on active Requirements), the untagged integration Requirements and the
uncovered scope; anyone who can read the Opportunity may read it. Products, industries and
catalogue entries are unique per test, as the database is shared."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.auth_tokens import auth_app
from tests.conftest import make_client
from tests.test_health import assert_problem
from tests.test_knowledge_checklists import _author, _entry, _published, _ready, _retire_entry
from tests.test_knowledge_coverage import _source
from tests.test_opportunities import BASE, PSE, _add, _create, _if_match, _user
from tests.test_role_admin import _admin


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _context(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/gaps/context", headers=headers)


def _requirement(
    client: TestClient, headers: dict[str, str], opp_id: str, classification: str = "integration"
) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/{opp_id}/requirements",
        headers=headers,
        json={"text": f"Requirement {uuid4().hex}.", "classification": classification},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _tag(
    client: TestClient, headers: dict[str, str], opp_id: str, item: dict[str, Any], ids: list[str]
) -> dict[str, Any]:
    response = client.put(
        f"{BASE}/{opp_id}/requirements/{item['id']}/integration-types",
        headers={**headers, **_if_match(item["row_version"])},
        json={"integration_type_ids": ids},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _opportunity(client: TestClient, engine: Engine, **fields: Any) -> tuple[dict[str, str], Any]:
    headers, _ = _user(client, engine, "Owner Person", PSE)
    tag = uuid4().hex
    body = {"products": [f"Product {tag}"], "industry": f"Industry {tag}", **fields}
    return headers, _create(client, headers, **body)


def test_nothing_in_scope_applies_and_the_product_is_uncovered(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, opp = _opportunity(client, sync_engine)
    _requirement(client, headers, opp["id"], "functional")

    response = _context(client, headers, opp["id"])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "applicable_checklists": [],
        "untagged_integration_count": 0,
        "uncovered": {"products": opp["products"], "integration_types": []},
    }


def test_the_context_composes_checklists_untagged_and_uncovered_scope(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    tag = uuid4().hex
    covered_product, bare_product = f"Covered {tag}", f"Bare {tag}"
    headers, opp = _opportunity(
        client, sync_engine, products=[covered_product, bare_product], industry=f"Ind {tag}"
    )
    covered_type, bare_type, other_type = (_entry(client, admin) for _ in range(3))
    by_product = _published(
        client, author, _ready(client, author, name=f"A {tag}", products=[covered_product])
    )
    by_type = _published(
        client,
        author,
        _ready(client, author, name=f"B {tag}", products=[], integration_type_ids=[covered_type]),
    )
    by_industry = _published(
        client,
        author,
        _ready(client, author, name=f"C {tag}", products=[], industry=f"  IND {tag.upper()}"),
    )
    _published(  # scoped by a type no active Requirement carries
        client, author, _ready(client, author, products=[], integration_type_ids=[other_type])
    )
    _source(sync_engine, covered_product, (UUID(covered_type),), embeds=["ready"])
    first, second = (
        _requirement(client, headers, opp["id"]),
        _requirement(client, headers, opp["id"]),
    )
    _requirement(client, headers, opp["id"])  # untagged
    _requirement(client, headers, opp["id"], "functional")  # not an integration Requirement
    _tag(client, headers, opp["id"], first, [covered_type])
    _tag(client, headers, opp["id"], second, [bare_type, covered_type])
    # A deleted Requirement's tags don't count.
    gone = _tag(client, headers, opp["id"], _requirement(client, headers, opp["id"]), [other_type])
    deleted = client.post(
        f"{BASE}/{opp['id']}/requirements/{gone['id']}/delete",
        headers={**headers, **_if_match(gone["row_version"])},
        json={"reason": "Out of scope."},
    )
    assert deleted.status_code == 200, deleted.text

    response = _context(client, headers, opp["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable_checklists"] == [
        {
            "checklist_id": c["id"],
            "version": 1,
            "name": c["name"],
            "domain": c["domain"],
        }
        for c in (by_product, by_type, by_industry)
    ]
    assert body["untagged_integration_count"] == 1
    bare_name = client.get(f"/api/v1/catalogue/entries/{bare_type}", headers=admin).json()["name"]
    assert body["uncovered"] == {
        "products": [bare_product],
        "integration_types": [{"id": bare_type, "name": bare_name}],
    }
    # A tag retired since stays on its Requirement but is no longer reported as uncovered.
    _retire_entry(client, admin, bare_type)
    retired = _context(client, headers, opp["id"]).json()
    assert retired["uncovered"]["integration_types"] == []


def test_a_sales_rep_may_read_it_and_an_outsider_gets_404(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, opp = _opportunity(client, sync_engine)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    outsider, _ = _user(client, sync_engine, "Outsider Person", PSE)

    assert _context(client, rep, opp["id"]).status_code == 200
    hidden = _context(client, outsider, opp["id"])
    unknown = _context(client, headers, str(uuid4()))

    for response in (hidden, unknown):
        assert response.status_code == 404
        assert_problem(response.json(), 404, "not_found")
