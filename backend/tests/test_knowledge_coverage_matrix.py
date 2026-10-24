"""Knowledge coverage (Story 3.5) against a real, migrated Postgres as psa_app: the spec's I/O
matrix (Ready, all stale, one kind, neither, excluded, industry only, no role), the pairing
rules for Checklist scopes, the product union and its order, Opportunity products respecting
visibility, and `get_pair_coverage` for other modules.

Sources are made Ready through the real parse and embed jobs (`_ready`, with the Ollama
stub). Every test uses its own products and Integration Types, since the database is shared
and a Checklist with products but no Integration Types covers every column."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.knowledge.application import jobs as knowledge_jobs
from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import CoveragePair
from app.platform.config import Settings
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_knowledge_checklists import BASE as CHECKLISTS
from tests.test_knowledge_checklists import _author, _item, _published, _retire_entry
from tests.test_knowledge_checklists import _create as _create_checklist
from tests.test_knowledge_checklists import _saved as _saved_checklist
from tests.test_knowledge_embedding import (
    _MINE,
    OllamaStub,
    _drain,
    _gateway_settings,
    _ready,
    _register,
)
from tests.test_knowledge_sources import BASE as SOURCES
from tests.test_knowledge_sources import _backdate, _if_match
from tests.test_opportunities import _create as _create_opportunity
from tests.test_role_admin import _admin, _signed_in

COVERAGE = "/api/v1/knowledge/coverage"
STALE_MONTHS = 12  # The default `PSA_KNOWLEDGE_STALE_MONTHS`.


# The embedding tests' fixtures: `_ready` runs the parse and embed jobs of this test's Sources
# (`_MINE`) against the Ollama stub.


@pytest.fixture
def ollama() -> OllamaStub:
    return OllamaStub()


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(root))
    monkeypatch.setattr(
        knowledge_jobs,
        "parse_settings",
        lambda: Settings(
            storage_dir=root,
            parse_timeout_s=60,
            knowledge_chunk_chars=400,
            knowledge_chunk_overlap_chars=80,
        ),
    )
    return root


@pytest.fixture(autouse=True)
def _own_sources() -> Iterator[None]:
    _MINE.clear()
    yield
    _MINE.clear()


@pytest.fixture
def client(db_url: str, storage_dir: Path, ollama: OllamaStub) -> Iterator[TestClient]:
    app = auth_app(db_url)
    app.state.model_gateway = ModelGateway(
        _gateway_settings(db_url), app.state.engine, transport=httpx.MockTransport(ollama.handle)
    )
    with make_client(app) as c:
        yield c


def _product(label: str = "Product") -> str:
    return f"{label} {uuid4().hex[:10]}"


def _type(client: TestClient, admin: dict[str, str]) -> str:
    resp = client.post(
        "/api/v1/catalogue/entries",
        headers=admin,
        json={
            "kind": "integration_type",
            "code": f"V-{uuid4().hex[:8]}",
            "name": f"Type {uuid4().hex}",
            "definition": "Exchange of documents.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]  # type: ignore[no-any-return]


def _checklist(
    client: TestClient,
    author: dict[str, str],
    *,
    products: list[str] | None = None,
    industry: str | None = None,
    types: list[str] | None = None,
    publish: bool = True,
    name: str | None = None,
) -> dict[str, Any]:
    created = _create_checklist(client, author, **({"name": name} if name else {}))
    saved = _saved_checklist(
        client,
        author,
        created,
        products=products or [],
        industry=industry,
        integration_type_ids=types or [],
        items=[_item()],
    )
    return _published(client, author, saved) if publish else saved


def _matrix(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(COVERAGE, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _row(matrix: dict[str, Any], product: str) -> dict[str, Any] | None:
    return next((r for r in matrix["rows"] if r["product"] == product), None)


def _cell(matrix: dict[str, Any], product: str, type_id: str) -> dict[str, Any]:
    row = _row(matrix, product)
    assert row is not None, f"no row for {product}"
    columns = [t["id"] for t in matrix["integration_types"]]
    assert [c["integration_type_id"] for c in row["cells"]] == columns
    return next(c for c in row["cells"] if c["integration_type_id"] == type_id)


def _counts(cell: dict[str, Any]) -> tuple[str, int, int, int]:
    return cell["status"], cell["sources"], cell["stale"], cell["checklists"]


def _get_pair_coverage(db_url: str, products: list[str], types: list[str]) -> list[CoveragePair]:
    async def go() -> list[CoveragePair]:
        engine = create_async_engine(db_url)
        try:
            async with unit_of_work(engine) as uow:
                return await knowledge.get_pair_coverage(
                    uow,
                    products=products,
                    integration_type_ids=[UUID(t) for t in types],
                    stale_months=STALE_MONTHS,
                )
        finally:
            await engine.dispose()

    return run_async(go())


# --- the I/O matrix --------------------------------------------------------------------------


def test_a_fresh_ready_source_and_a_published_checklist_are_ready(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    product, type_id = _product(), _type(client, admin)
    _ready(client, db_url, ollama, admin, type_id, product=product)
    _checklist(client, author, products=[product], types=[type_id])

    matrix = _matrix(client, admin)
    assert _counts(_cell(matrix, product, type_id)) == ("ready", 1, 0, 1)
    assert matrix["stale_months"] == STALE_MONTHS
    column = next(t for t in matrix["integration_types"] if t["id"] == type_id)
    assert column["name"].startswith("Type ") and column["code"].startswith("V-")


def test_sources_that_are_all_stale_make_the_cell_partial(
    client: TestClient, db_url: str, ollama: OllamaStub, sync_engine: Engine
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    product, type_id = _product(), _type(client, admin)
    first = _ready(client, db_url, ollama, admin, type_id, product=product)
    second = _ready(client, db_url, ollama, admin, type_id, product=product)
    _checklist(client, author, products=[product], types=[type_id])
    _backdate(sync_engine, first["id"], 13)
    _backdate(sync_engine, second["id"], 13)

    assert _counts(_cell(_matrix(client, admin), product, type_id)) == ("partial", 2, 2, 1)

    # One fresh Source again is enough for Ready.
    _backdate(sync_engine, second["id"], 0)
    assert _counts(_cell(_matrix(client, admin), product, type_id)) == ("ready", 2, 1, 1)


def test_only_one_kind_is_partial(client: TestClient, db_url: str, ollama: OllamaStub) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    sourced, listed, type_id = _product(), _product(), _type(client, admin)
    _ready(client, db_url, ollama, admin, type_id, product=sourced)
    _checklist(client, author, products=[listed], types=[type_id])

    matrix = _matrix(client, admin)
    assert _counts(_cell(matrix, sourced, type_id)) == ("partial", 1, 0, 0)
    assert _counts(_cell(matrix, listed, type_id)) == ("partial", 0, 0, 1)


def test_a_product_only_on_an_opportunity_is_a_row_of_missing_cells(client: TestClient) -> None:
    admin, _ = _admin(client)
    engineer, _ = _signed_in(client, "Engineer", "presales_engineer")
    product, first, second = _product(), _type(client, admin), _type(client, admin)
    _create_opportunity(client, engineer, products=[product])

    matrix = _matrix(client, admin)
    for type_id in (first, second):
        assert _counts(_cell(matrix, product, type_id)) == ("missing", 0, 0, 0)


def test_retired_unready_and_unpublished_knowledge_is_not_counted(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    product, type_id = _product(), _type(client, admin)
    # A Source retired after it was Ready.
    retired = _ready(client, db_url, ollama, admin, type_id, product=product)
    current = client.get(f"{SOURCES}/{retired['id']}", headers=admin).json()
    resp = client.post(
        f"{SOURCES}/{retired['id']}/retire",
        headers={**admin, **_if_match(current["row_version"])},
        json={"reason": "Superseded"},
    )
    assert resp.status_code == 200, resp.text
    # A Source not yet parsed or embedded (its jobs never run).
    _register(client, admin, [type_id], "# Pending\n\nNot embedded yet.\n", product=product)
    # A retired Checklist and a Checklist with only a draft.
    gone = _checklist(client, author, products=[product], types=[type_id])
    resp = client.post(
        f"{CHECKLISTS}/{gone['id']}/retire",
        headers={**author, **_if_match(gone["row_version"])},
        json={"reason": "Old"},
    )
    assert resp.status_code == 200, resp.text
    _checklist(client, author, products=[product], types=[type_id], publish=False)

    assert _get_pair_coverage(db_url, [product], [type_id])[0].model_dump() == {
        "product": product,
        "integration_type_id": type_id,
        "sources": 0,
        "stale": 0,
        "checklists": 0,
        "status": "missing",
    }
    # Nothing that counts names the product, so it has no row at all.
    assert _row(_matrix(client, admin), product) is None


def test_an_industry_only_checklist_is_listed_under_its_industry(client: TestClient) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    industry = f"Retail {uuid4().hex[:8]}"
    name = f"Retail baseline {uuid4().hex[:6]}"
    _checklist(client, author, industry=industry, name=name)
    _checklist(client, author, industry=f"  {industry.upper()} ", name=f"Z {name}")
    # Industry with products is a matrix Checklist, not an industry-only one.
    product, type_id = _product(), _type(client, admin)
    _checklist(client, author, products=[product], industry=industry, types=[type_id])

    matrix = _matrix(client, admin)
    (entry,) = [i for i in matrix["industries"] if i["industry"].casefold() == industry.casefold()]
    assert entry == {"industry": industry, "checklists": 2, "names": [name, f"Z {name}"]}
    assert _counts(_cell(matrix, product, type_id)) == ("partial", 0, 0, 1)
    names = [i["industry"].casefold() for i in matrix["industries"]]
    assert names == sorted(names)


def test_a_caller_with_no_role_gets_403(client: TestClient) -> None:
    nobody, _ = _signed_in(client, "Nobody")
    resp = client.get(COVERAGE, headers=nobody)
    assert resp.status_code == 403, resp.text
    assert_problem(resp.json(), 403, "forbidden")
    assert client.get(COVERAGE).status_code == 401


def test_every_role_can_read_coverage(client: TestClient) -> None:
    for role in (
        "presales_engineer",
        "sales_representative",
        "commercial",
        "delivery_manager",
        "head_of_delivery",
        "engineering_reviewer",
        "pm_reviewer",
        "security_reviewer",
        "platform_administrator",
    ):
        headers, _ = _signed_in(client, f"Reader {role}", role)
        assert client.get(COVERAGE, headers=headers).status_code == 200, role


# --- pairing ----------------------------------------------------------------------------------


def test_checklist_scopes_and_source_tags_pair_as_the_spec_says(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    p, q, r = _product("P"), _product("Q"), _product("R")
    t1, t2 = _type(client, admin), _type(client, admin)
    # A Source covers its one product with each of its tags.
    source = _register(client, admin, [t1, t2], "# Both\n\nTwo tags.\n", product=p)
    _drain(db_url, ollama)
    assert client.get(f"{SOURCES}/{source['id']}", headers=admin).json()["embed"]["status"] == (
        "ready"
    )
    # Products, no Integration Types: every column of those products (named in another case).
    _checklist(client, author, products=[f"  {p.upper()} "])
    # Integration Types, no products: every row of those columns.
    _checklist(client, author, types=[t1])
    # Both: only their pairs.
    _checklist(client, author, products=[q], types=[t2])
    # A third product, so the types-only Checklist has another row to reach.
    _checklist(client, author, products=[r], types=[t2])

    matrix = _matrix(client, admin)
    assert _counts(_cell(matrix, p, t1)) == ("ready", 1, 0, 2)
    assert _counts(_cell(matrix, p, t2)) == ("ready", 1, 0, 1)
    assert _counts(_cell(matrix, q, t1)) == ("partial", 0, 0, 1)
    assert _counts(_cell(matrix, q, t2)) == ("partial", 0, 0, 1)
    # The types-only Checklist reaches other products' rows too.
    assert _counts(_cell(matrix, r, t1)) == ("partial", 0, 0, 1)
    assert _counts(_cell(matrix, r, t2)) == ("partial", 0, 0, 1)


def test_rows_are_the_union_of_products_sorted_ignoring_case(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    engineer, _ = _signed_in(client, "Engineer", "presales_engineer")
    stem = uuid4().hex[:8]
    alpha, beta, gamma = f"alpha {stem}", f"Beta {stem}", f"gamma {stem}"
    type_id = _type(client, admin)
    _ready(client, db_url, ollama, admin, type_id, product=beta)
    _checklist(client, author, products=[alpha], types=[type_id])
    _create_opportunity(client, engineer, products=[gamma, f"BETA {stem}"])

    matrix = _matrix(client, admin)
    mine = [r["product"] for r in matrix["rows"] if r["product"].endswith(stem)]
    # One row per product ignoring case, spelled as first seen (the Source's).
    assert mine == [alpha, beta, gamma]
    keys = [r["product"].casefold() for r in matrix["rows"]]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_columns_are_the_active_integration_types(client: TestClient) -> None:
    admin, _ = _admin(client)
    kept, retired = _type(client, admin), _type(client, admin)
    _retire_entry(client, admin, retired)
    ids = [t["id"] for t in _matrix(client, admin)["integration_types"]]
    assert kept in ids and retired not in ids


def test_opportunity_products_follow_what_the_caller_can_read(client: TestClient) -> None:
    owner, _ = _signed_in(client, "Owner", "presales_engineer")
    stranger, _ = _signed_in(client, "Stranger", "presales_engineer")
    head, _ = _signed_in(client, "Head", "head_of_delivery")
    admin, _ = _admin(client)
    product = _product("Private")
    _create_opportunity(client, owner, products=[product])

    assert _row(_matrix(client, owner), product) is not None
    assert _row(_matrix(client, stranger), product) is None
    assert _row(_matrix(client, head), product) is not None
    assert _row(_matrix(client, admin), product) is not None


# --- get_pair_coverage -------------------------------------------------------------------------


def test_get_pair_coverage_counts_exactly_the_pairs_asked_for(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    p, q = _product("P"), _product("Q")
    t1, t2 = _type(client, admin), _type(client, admin)
    _ready(client, db_url, ollama, admin, t1, product=p)
    _checklist(client, author, products=[p], types=[t1])
    _checklist(client, author, products=[q])

    pairs = _get_pair_coverage(db_url, [f" {p.upper()} ", "", p, q], [t1, t2, t1])
    assert [(x.product, x.integration_type_id) for x in pairs] == [
        (p.upper(), t1),
        (p.upper(), t2),
        (q, t1),
        (q, t2),
    ]
    assert [(x.status, x.sources, x.stale, x.checklists) for x in pairs] == [
        ("ready", 1, 0, 1),
        ("missing", 0, 0, 0),
        ("partial", 0, 0, 1),
        ("partial", 0, 0, 1),
    ]
    assert _get_pair_coverage(db_url, [], [t1]) == []
    assert _get_pair_coverage(db_url, [p], []) == []
    # Retired and unknown Integration Types are dropped, though `q`'s products-only
    # Checklist would otherwise count for them.
    retired = _type(client, admin)
    _retire_entry(client, admin, retired)
    pairs = _get_pair_coverage(db_url, [q], [retired, str(uuid4()), t2])
    assert [(x.integration_type_id, x.checklists) for x in pairs] == [(t2, 1)]
    assert _get_pair_coverage(db_url, [q], [retired]) == []


def test_only_the_latest_version_of_a_source_counts(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    product, type_id = _product(), _type(client, admin)
    source = _ready(client, db_url, ollama, admin, type_id, product=product)
    assert _get_pair_coverage(db_url, [product], [type_id])[0].sources == 1

    current = client.get(f"{SOURCES}/{source['id']}", headers=admin).json()
    resp = client.post(
        f"{SOURCES}/{source['id']}/versions",
        headers={**admin, **_if_match(current["row_version"])},
        params={"product_version": "3.0"},
        files={"file": ("v2.md", f"# V2\n\n{uuid4()}\n".encode(), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    # Version 2 is not embedded yet, so the Source no longer counts.
    assert _get_pair_coverage(db_url, [product], [type_id])[0].sources == 0

    _drain(db_url, ollama)
    assert _get_pair_coverage(db_url, [product], [type_id])[0].sources == 1
    assert _counts(_cell(_matrix(client, admin), product, type_id)) == ("partial", 1, 0, 0)
