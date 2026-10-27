"""Knowledge Graph (Story 3.6) against a real, migrated Postgres as psa_app: the spec's I/O
matrix (Ready pair, stale Source, pipeline states, Opportunity-only product, industry-only
Checklist, what is left out, who may read it), the edge kinds and the node fields.

Sources are made Ready through the real parse and embed jobs (`_ready`, with the Ollama stub).
Every test uses its own products and Integration Types. The database is shared, and a
Checklist scoped by products only (or Integration Types only) reaches every column (or row),
so the tests that assert a product's or an Integration Type's status first retire such
Checklists left behind by earlier tests (`_without_wildcard_checklists`)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.knowledge.application import jobs as knowledge_jobs
from app.platform.config import Settings
from app.platform.model_gateway.gateway import ModelGateway
from tests.auth_tokens import auth_app
from tests.conftest import make_client
from tests.test_health import assert_problem
from tests.test_knowledge_checklists import BASE as CHECKLISTS
from tests.test_knowledge_checklists import _author, _retire_entry
from tests.test_knowledge_coverage_matrix import _checklist, _product, _type
from tests.test_knowledge_embedding import _MINE, OllamaStub, _gateway_settings, _ready, _register
from tests.test_knowledge_sources import BASE as SOURCES
from tests.test_knowledge_sources import _backdate, _if_match
from tests.test_opportunities import _create as _create_opportunity
from tests.test_role_admin import _admin, _signed_in

GRAPH = "/api/v1/knowledge/graph"
STALE_MONTHS = 12


# The coverage tests' fixtures: `_ready` runs this test's parse and embed jobs (`_MINE`) against
# the Ollama stub.


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


def _graph(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(GRAPH, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    found = [n for n in graph["nodes"] if n["id"] == node_id]
    assert len(found) == 1, f"{node_id}: {len(found)} nodes"
    return found[0]


def _has_node(graph: dict[str, Any], node_id: str) -> bool:
    return any(n["id"] == node_id for n in graph["nodes"])


def _edges(graph: dict[str, Any], node_id: str) -> set[tuple[str, str, str]]:
    """The edges touching the node, as `(source, target, kind)`."""
    return {
        (e["source"], e["target"], e["kind"])
        for e in graph["edges"]
        if node_id in (e["source"], e["target"])
    }


def _pid(product: str) -> str:
    return f"product:{product.strip().casefold()}"


def _tid(type_id: str) -> str:
    return f"integration_type:{type_id}"


def _sid(source: dict[str, Any]) -> str:
    return f"source:{source['id']}"


def _cid(checklist: dict[str, Any]) -> str:
    return f"checklist:{checklist['id']}"


def _without_wildcard_checklists(engine: Engine) -> None:
    """Retire the active Checklists scoped by products only or by Integration Types only:
    they cover every column or row, so they would touch this test's products and types."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE knowledge_checklists c "
                "SET status = 'retired', retired_reason = 'Graph test isolation', draft = NULL "
                "WHERE c.status = 'active' AND (cardinality(c.products) = 0) <> NOT EXISTS "
                "(SELECT 1 FROM knowledge_checklist_scope_tags t WHERE t.checklist_id = c.id)"
            )
        )


def _fail_parse(engine: Engine, source_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE knowledge_source_parses SET status = 'failed', error_code = 'unreadable' "
                "WHERE source_id = :s"
            ),
            {"s": source_id},
        )


# --- the I/O matrix --------------------------------------------------------------------------


def test_a_ready_pair_links_everything_and_is_ready(
    client: TestClient, db_url: str, ollama: OllamaStub, sync_engine: Engine
) -> None:
    _without_wildcard_checklists(sync_engine)
    admin, admin_id = _admin(client, "Graph Admin")
    author, author_id = _signed_in(client, "Graph Author", "security_reviewer")
    product, type_id = _product(), _type(client, admin)
    source = _ready(client, db_url, ollama, admin, type_id, product=product)
    checklist = _checklist(client, author, products=[product], types=[type_id])

    graph = _graph(client, admin)
    p, t, s, c = _pid(product), _tid(type_id), _sid(source), _cid(checklist)

    assert _edges(graph, p) == {
        (s, p, "linked"),
        (c, p, "linked"),
        (p, t, "linked"),
    }
    assert _edges(graph, t) == {(s, t, "linked"), (c, t, "linked"), (p, t, "linked")}
    for node_id in (p, t, s, c):
        node = _node(graph, node_id)
        assert (node["status"], node["score"]) == ("ready", 100), node

    product_node = _node(graph, p)
    assert product_node["type"] == "product" and product_node["label"] == product
    assert product_node["owner"] is None and product_node["last_reviewed_on"] is None
    assert product_node["can_review"] is False and product_node["row_version"] is None
    type_node = _node(graph, t)
    assert type_node["type"] == "integration_type" and type_node["label"].startswith("Type ")

    source_node = _node(graph, s)
    assert source_node["type"] == "source"
    assert source_node["label"] == source["title"]
    assert source_node["owner"] == {"id": str(admin_id), "name": "Graph Admin"}
    assert source_node["last_reviewed_on"] == datetime.now(UTC).date().isoformat()
    assert source_node["can_review"] is True
    assert source_node["row_version"] >= 1
    assert 360 <= source_node["stale_in_days"] <= 367

    checklist_node = _node(graph, c)
    assert checklist_node["type"] == "checklist" and checklist_node["label"] == checklist["name"]
    assert checklist_node["owner"] == {"id": str(author_id), "name": "Graph Author"}
    assert checklist_node["last_reviewed_on"] == datetime.now(UTC).date().isoformat()
    assert checklist_node["can_review"] is False and checklist_node["stale_in_days"] is None
    assert graph["stale_months"] == STALE_MONTHS

    # Another Checklist editor, neither admin nor owner, may not review it.
    other, _ = _signed_in(client, "Other Author", "engineering_reviewer")
    assert _node(_graph(client, other), s)["can_review"] is False


def test_a_stale_source_is_stale_and_its_pair_is_a_gap(
    client: TestClient, db_url: str, ollama: OllamaStub, sync_engine: Engine
) -> None:
    _without_wildcard_checklists(sync_engine)
    admin, _ = _admin(client)
    author = _author(client)
    product, type_id = _product(), _type(client, admin)
    source = _ready(client, db_url, ollama, admin, type_id, product=product)
    _checklist(client, author, products=[product], types=[type_id])
    _backdate(sync_engine, source["id"], 13)

    graph = _graph(client, admin)
    p, t, s = _pid(product), _tid(type_id), _sid(source)
    node = _node(graph, s)
    assert (node["status"], node["score"], node["stale_in_days"]) == ("stale", 75, 0)
    assert (p, t, "gap") in _edges(graph, p)
    assert (_node(graph, p)["status"], _node(graph, p)["score"]) == ("partial", 75)
    assert _node(graph, t)["status"] == "partial"

    # Mark reviewed clears it.
    current = client.get(f"{SOURCES}/{source['id']}", headers=admin).json()
    resp = client.post(
        f"{SOURCES}/{source['id']}/review",
        headers={**admin, **_if_match(current["row_version"])},
    )
    assert resp.status_code == 200, resp.text
    graph = _graph(client, admin)
    assert _node(graph, s)["status"] == "ready"
    assert (p, t, "linked") in _edges(graph, p)


def test_pipeline_states_are_embedding_and_embedding_failed_and_still_linked(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _ = _admin(client)
    product, type_id = _product(), _type(client, admin)
    pending = _register(client, admin, [type_id], "# Pending\n\nNot parsed yet.\n", product=product)
    failed = _register(client, admin, [type_id], "# Broken\n\nWon't parse.\n", product=product)
    _fail_parse(sync_engine, failed["id"])

    graph = _graph(client, admin)
    p, t = _pid(product), _tid(type_id)
    for source, status, score in ((pending, "embedding", 70), (failed, "embedding_failed", 15)):
        s = _sid(source)
        node = _node(graph, s)
        assert (node["status"], node["score"]) == (status, score)
        assert _edges(graph, s) == {(s, p, "linked"), (s, t, "linked")}
    # Neither counts as documentation: the pair is uncovered, so it has no edge.
    assert not any({e[0], e[1]} == {p, t} for e in _edges(graph, p))
    assert (_node(graph, p)["status"], _node(graph, p)["score"]) == ("missing", 0)


def test_a_product_only_on_an_opportunity_is_missing_with_no_edges(
    client: TestClient, sync_engine: Engine
) -> None:
    _without_wildcard_checklists(sync_engine)
    admin, _ = _admin(client)
    engineer, _ = _signed_in(client, "Engineer", "presales_engineer")
    product = _product("Opportunity")
    _create_opportunity(client, engineer, products=[product])

    graph = _graph(client, admin)
    node = _node(graph, _pid(product))
    assert (node["status"], node["score"], node["label"]) == ("missing", 0, product)
    assert _edges(graph, _pid(product)) == set()


def test_an_industry_only_checklist_has_no_edges(client: TestClient) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    checklist = _checklist(client, author, industry=f"Retail {_product()}")

    graph = _graph(client, admin)
    node = _node(graph, _cid(checklist))
    assert (node["status"], node["score"]) == ("missing", 0)
    assert _edges(graph, _cid(checklist)) == set()


def test_retired_and_unpublished_knowledge_and_retired_types_are_left_out(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client)
    author = _author(client)
    product, type_id, retired_type = _product(), _type(client, admin), _type(client, admin)
    retired = _ready(client, db_url, ollama, admin, type_id, product=product)
    current = client.get(f"{SOURCES}/{retired['id']}", headers=admin).json()
    resp = client.post(
        f"{SOURCES}/{retired['id']}/retire",
        headers={**admin, **_if_match(current["row_version"])},
        json={"reason": "Superseded"},
    )
    assert resp.status_code == 200, resp.text
    gone = _checklist(client, author, products=[product], types=[type_id])
    resp = client.post(
        f"{CHECKLISTS}/{gone['id']}/retire",
        headers={**author, **_if_match(gone["row_version"])},
        json={"reason": "Old"},
    )
    assert resp.status_code == 200, resp.text
    draft = _checklist(client, author, products=[product], types=[type_id], publish=False)
    _retire_entry(client, admin, retired_type)

    graph = _graph(client, admin)
    for node_id in (_sid(retired), _cid(gone), _cid(draft), _tid(retired_type), _pid(product)):
        assert not _has_node(graph, node_id), node_id
    assert not any(retired_type in (e["source"] + e["target"]) for e in graph["edges"])


def test_a_partial_pair_is_a_gap_edge_and_tags_of_retired_types_are_dropped(
    client: TestClient, db_url: str, ollama: OllamaStub, sync_engine: Engine
) -> None:
    _without_wildcard_checklists(sync_engine)
    admin, _ = _admin(client)
    author = _author(client)
    sourced, listed = _product("Sourced"), _product("Listed")
    t1, t2 = _type(client, admin), _type(client, admin)
    source = _ready(client, db_url, ollama, admin, t1, product=sourced)
    # Covered only by a Checklist.
    checklist = _checklist(client, author, products=[listed], types=[t1, t2])
    _retire_entry(client, admin, t2)

    graph = _graph(client, admin)
    assert _edges(graph, _pid(sourced)) == {
        (_sid(source), _pid(sourced), "linked"),
        (_pid(sourced), _tid(t1), "gap"),
    }
    assert _edges(graph, _pid(listed)) == {
        (_cid(checklist), _pid(listed), "linked"),
        (_pid(listed), _tid(t1), "gap"),
    }
    assert _edges(graph, _cid(checklist)) == {
        (_cid(checklist), _pid(listed), "linked"),
        (_cid(checklist), _tid(t1), "linked"),
    }
    assert (_node(graph, _pid(sourced))["status"], _node(graph, _pid(sourced))["score"]) == (
        "partial",
        50,
    )
    assert _node(graph, _cid(checklist))["status"] == "partial"
    assert _node(graph, _sid(source))["score"] == 50
    assert _node(graph, _tid(t1))["status"] == "partial"


# --- who may read it -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", ["engineering_reviewer", "pm_reviewer", "security_reviewer", "platform_administrator"]
)
def test_checklist_editors_and_admins_can_read_the_graph(client: TestClient, role: str) -> None:
    headers, _ = _signed_in(client, f"Reader {role}", role)
    assert client.get(GRAPH, headers=headers).status_code == 200


@pytest.mark.parametrize(
    "role",
    [
        "presales_engineer",
        "sales_representative",
        "commercial",
        "delivery_manager",
        "head_of_delivery",
    ],
)
def test_other_roles_get_403(client: TestClient, role: str) -> None:
    headers, _ = _signed_in(client, f"Reader {role}", role)
    resp = client.get(GRAPH, headers=headers)
    assert resp.status_code == 403, resp.text
    assert_problem(resp.json(), 403, "forbidden")


def test_no_role_gets_403_and_no_token_401(client: TestClient) -> None:
    nobody, _ = _signed_in(client, "Nobody")
    assert client.get(GRAPH, headers=nobody).status_code == 403
    assert client.get(GRAPH).status_code == 401


def test_node_ids_are_unique_and_every_edge_joins_two_nodes(client: TestClient) -> None:
    admin, _ = _admin(client)
    graph = _graph(client, admin)
    ids = [n["id"] for n in graph["nodes"]]
    assert len(ids) == len(set(ids))
    known = set(ids)
    for edge in graph["edges"]:
        assert edge["source"] in known and edge["target"] in known, edge
    for node in graph["nodes"]:
        prefix, _, rest = node["id"].partition(":")
        assert prefix == node["type"] and rest
        if prefix != "product":
            UUID(rest)
