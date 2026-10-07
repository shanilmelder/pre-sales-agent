"""Knowledge Sources (Story 3.2) against a real, migrated Postgres as psa_app: the spec's
I/O matrix (register, bad file, retired tag, parse failure and retry, stale and Mark
reviewed, non-owner 403, 428/412), versions staying readable, signed downloads, the trace
and the `knowledge.parse_source` job through the real runner. Files go to a temp
`PSA_STORAGE_DIR`; jobs are claimed only for the current test's Sources."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.knowledge.adapters.parse_runner import ParseTimeoutError
from app.modules.knowledge.application import jobs as knowledge_jobs
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import queue as q
from app.platform.jobs.models import PlatformJob
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_intake_filetypes import DOCX
from tests.test_intake_parsers import FIXTURES
from tests.test_role_admin import _admin, _grant, _signed_in

BASE = "/api/v1/knowledge/sources"
CATALOGUE = "/api/v1/catalogue/entries"
JOB_TYPE = "knowledge.parse_source"
LEASE = LeaseSettings(lease_s=30, heartbeat_s=5)
CODES = {
    401: "token_missing",
    403: "forbidden",
    404: "not_found",
    409: "knowledge_source_retired",
    412: "row_version_mismatch",
    422: "validation_error",
    428: "if_match_required",
}
_MINE: list[UUID] = []
"""The current test's Sources: `_drain` runs only their parse jobs."""


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(root))
    monkeypatch.setattr(
        knowledge_jobs, "parse_settings", lambda: Settings(storage_dir=root, parse_timeout_s=60)
    )
    return root


@pytest.fixture(autouse=True)
def _own_sources() -> Iterator[None]:
    _MINE.clear()
    yield
    _MINE.clear()


@pytest.fixture
def client(db_url: str, storage_dir: Path) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _problem(resp: Response, status: int, code: str | None = None) -> None:
    assert resp.status_code == status, resp.text
    assert_problem(resp.json(), status, code or CODES[status])


def _if_match(row_version: int) -> dict[str, str]:
    return {"If-Match": f'"{row_version}"'}


def _text_file(label: str = "") -> bytes:
    """A Markdown document, unique per call (`platform_files` is shared across tests)."""
    return f"# Guide {label}\n\nPorts: 40. Id {uuid4()}\n".encode()


def _tag(client: TestClient, admin: dict[str, str]) -> dict[str, Any]:
    resp = client.post(
        CATALOGUE,
        headers=admin,
        json={
            "kind": "integration_type",
            "code": f"T-{uuid4().hex[:8]}",
            "name": f"Type {uuid4().hex}",
            "definition": "Exchange of documents.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _register(
    client: TestClient,
    headers: dict[str, str],
    tags: list[str],
    *,
    name: str = "guide.md",
    data: bytes | None = None,
    **fields: Any,
) -> Response:
    params: list[tuple[str, str]] = [
        ("title", fields.pop("title", "Install guide")),
        ("product", fields.pop("product", "AutoStore")),
        ("product_version", fields.pop("product_version", "2.1")),
        *[("integration_type_ids", t) for t in tags],
        *[(k, str(v)) for k, v in fields.items()],
    ]
    return client.post(
        BASE,
        headers=headers,
        params=params,
        files={"file": (name, _text_file() if data is None else data, "application/octet-stream")},
    )


def _registered(
    client: TestClient, headers: dict[str, str], tags: list[str], **kwargs: Any
) -> dict[str, Any]:
    resp = _register(client, headers, tags, **kwargs)
    assert resp.status_code == 201, resp.text
    source: dict[str, Any] = resp.json()
    _MINE.append(UUID(source["id"]))
    return source


def _events(engine: Engine, source_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE subject_id = :s "
                    "AND event_type LIKE 'knowledge.source.%' ORDER BY occurred_at, id"
                ),
                {"s": source_id},
            ).mappings()
        ]


def _jobs(engine: Engine, source_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM platform_jobs WHERE job_type = :t "
                    "AND payload->>'source_id' = :s ORDER BY created_at, id"
                ),
                {"t": JOB_TYPE, "s": source_id},
            ).mappings()
        ]


def _parse_row(engine: Engine, source_id: str, version: int = 1) -> dict[str, Any]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                sa.text(
                    "SELECT * FROM knowledge_source_parses WHERE source_id = :s AND version = :v"
                ),
                {"s": source_id, "v": version},
            )
            .mappings()
            .one()
        )


def _backdate(engine: Engine, source_id: str, months: int) -> None:
    """Pretend the Source was last reviewed `months` (30-day) months ago."""
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE knowledge_sources SET last_reviewed_on = :d WHERE id = :s"),
            {"d": datetime.now(UTC).date() - timedelta(days=30 * months), "s": source_id},
        )


async def _claim_mine(engine: AsyncEngine) -> q.ClaimedJob | None:
    t = PlatformJob
    eligible = sa.or_(
        t.status.in_(("queued", "failed_retrying")),
        sa.and_(t.status == "running", t.lease_expires_at < sa.func.now()),
    )
    mine = [str(i) for i in _MINE]
    next_id = (
        sa.select(t.id)
        .where(t.job_type == JOB_TYPE, t.payload["source_id"].astext.in_(mine), eligible)
        .order_by(t.priority, t.run_after, t.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        sa.update(t)
        .where(t.id == next_id)
        .values(
            status="running",
            lease_owner="test-worker",
            lease_expires_at=sa.func.now() + timedelta(seconds=LEASE.lease_s),
            attempts=t.attempts + 1,
            updated_at=sa.func.now(),
        )
        .returning(t.id, t.job_type, t.payload, t.attempts, t.opportunity_id)
    )
    async with unit_of_work(engine) as uow:
        row = (await uow.session.execute(statement)).one_or_none()
    if row is None:
        return None
    return q.ClaimedJob(
        id=row.id,
        job_type=row.job_type,
        payload=row.payload,
        attempts=row.attempts,
        opportunity_id=row.opportunity_id,
        lease_owner="test-worker",
    )


def _drain(db_url: str, *, max_runs: int = 10) -> list[str]:
    async def scenario() -> list[str]:
        engine = create_engine(Settings(database_url=db_url))
        outcomes: list[str] = []
        try:
            for _ in range(max_runs):
                job = await _claim_mine(engine)
                if job is None:
                    break
                outcomes.append(await run_job(engine, job, LEASE))
        finally:
            await engine.dispose()
        return outcomes

    return run_async(scenario())


def _admin_and_tag(
    client: TestClient, engine: Engine, name: str = "Knowledge Admin"
) -> tuple[dict[str, str], UUID, dict[str, Any]]:
    admin, admin_id = _admin(client, engine, name)
    return admin, admin_id, _tag(client, admin)


def _expert(
    client: TestClient, engine: Engine, name: str = "Expert"
) -> tuple[dict[str, str], UUID]:
    headers, user_id = _signed_in(client, name)
    _grant(engine, user_id, "engineering_reviewer")
    return headers, user_id


# --- register ---------------------------------------------------------------------------------


def test_register_stores_the_file_queues_a_parse_and_traces(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    admin, admin_id, tag = _admin_and_tag(client, sync_engine)
    data = _text_file("register")
    resp = _register(client, admin, [tag["id"]], name="Guide.MD", data=data, title="  Guide ")
    assert resp.status_code == 201, resp.text
    source = resp.json()
    _MINE.append(UUID(source["id"]))

    today = datetime.now(UTC).date().isoformat()
    assert resp.headers["ETag"] == '"1"'
    assert (source["title"], source["product"], source["product_version"]) == (
        "Guide",
        "AutoStore",
        "2.1",
    )
    assert source["owner"]["id"] == str(admin_id)  # defaults to the uploader
    assert source["integration_types"] == [
        {"id": tag["id"], "code": tag["code"], "name": tag["name"], "retired": False}
    ]
    assert (source["version"], source["version_count"], source["size_bytes"]) == (1, 1, len(data))
    assert (source["last_reviewed_on"], source["stale"], source["status"]) == (
        today,
        False,
        "active",
    )
    assert source["parse"] == {"status": "queued", "error_code": None}
    assert source["filename"] == "Guide.MD"
    sha = hashlib.sha256(data).hexdigest()
    assert (storage_dir / "sha256" / sha[:2] / sha[2:4] / sha).read_bytes() == data
    (job,) = _jobs(sync_engine, source["id"])
    assert job["status"] == "queued" and job["opportunity_id"] is None
    (event,) = _events(sync_engine, source["id"])
    assert event["event_type"] == "knowledge.source.registered"
    assert event["opportunity_id"] is None
    assert event["payload"] == {
        "version": 1,
        "owner_id": str(admin_id),
        "tag_count": 1,
        "size_bytes": len(data),
    }
    with sync_engine.connect() as conn:
        refs = conn.execute(
            sa.text("SELECT ref_count FROM platform_files WHERE sha256 = :s"), {"s": sha}
        ).scalar_one()
    assert refs == 1


def test_an_administrator_owns_by_default_and_experts_cannot_register(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, admin_id, tag = _admin_and_tag(client, sync_engine)
    mine = _registered(client, admin, [tag["id"]])
    assert mine["owner"]["id"] == str(admin_id)

    expert, _ = _expert(client, sync_engine)
    _, other_id = _expert(client, sync_engine, "Other Expert")
    _problem(_register(client, expert, [tag["id"]]), 403)
    named = _registered(client, admin, [tag["id"]], owner_id=other_id)
    assert named["owner"]["id"] == str(other_id)


def test_roles_without_a_registering_role_are_403(client: TestClient, sync_engine: Engine) -> None:
    _, _, tag = _admin_and_tag(client, sync_engine)
    headers, user_id = _signed_in(client, "Sales Person")
    _grant(sync_engine, user_id, "sales_representative")
    _problem(_register(client, headers, [tag["id"]]), 403)
    nobody, _ = _signed_in(client, "No Role")
    _problem(_register(client, nobody, [tag["id"]]), 403)


def test_an_owner_with_no_role_is_422(client: TestClient, sync_engine: Engine) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    _, roleless = _signed_in(client, "Roleless")
    _problem(_register(client, admin, [tag["id"]], owner_id=roleless), 422)


def test_a_retired_tag_is_422_and_nothing_is_stored(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    retired = client.post(
        f"{CATALOGUE}/{tag['id']}/retire",
        headers={**admin, **_if_match(tag["row_version"])},
        json={"reason": "obsolete"},
    )
    assert retired.status_code == 200
    resp = _register(client, admin, [tag["id"]])
    _problem(resp, 422)
    assert "Integration Type" in resp.json()["detail"]
    assert not storage_dir.exists() or not [p for p in storage_dir.rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    "fields",
    [{"title": " "}, {"product": ""}, {"product_version": "x" * 61}, {"title": "x" * 201}],
)
def test_invalid_fields_are_422(
    client: TestClient, sync_engine: Engine, fields: dict[str, Any]
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    _problem(_register(client, admin, [tag["id"]], **fields), 422)


def test_no_tag_a_work_package_or_an_unknown_entry_is_422(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _, _ = _admin_and_tag(client, sync_engine)
    _problem(_register(client, admin, []), 422)
    package = client.post(
        CATALOGUE,
        headers=admin,
        json={
            "kind": "work_package",
            "code": f"W-{uuid4().hex[:8]}",
            "name": f"WP {uuid4().hex}",
            "definition": "Work.",
        },
    ).json()
    _problem(_register(client, admin, [package["id"]]), 422)
    _problem(_register(client, admin, [str(uuid4())]), 422)


@pytest.mark.parametrize(
    ("name", "data", "reason"),
    [
        ("notes.exe", b"MZ", "Rejected: .exe files aren't allowed"),
        ("notes", b"abc", "Rejected: files without an extension aren't allowed"),
        ("notes.eml", b"abc", "Rejected: .eml files aren't allowed"),
        ("report.pdf", b"not a pdf", "Rejected: the content doesn't match .pdf"),
        ("guide.docx", b"PK\x03\x04junk", "Rejected: the content doesn't match .docx"),
        ("guide.md", b"\xff\xfe\x00bad", "Rejected: the content doesn't match .md"),
        ("guide.txt", b"", "Rejected: the file is empty"),
    ],
)
def test_a_bad_file_is_rejected_with_its_reason_and_nothing_is_stored(
    client: TestClient, sync_engine: Engine, storage_dir: Path, name: str, data: bytes, reason: str
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    with sync_engine.connect() as conn:
        before = conn.execute(sa.text("SELECT count(*) FROM knowledge_sources")).scalar_one()
    resp = _register(client, admin, [tag["id"]], name=name, data=data)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] in {"file_type_not_allowed", "file_content_mismatch", "file_empty"}
    assert resp.json()["detail"] == reason
    with sync_engine.connect() as conn:
        after = conn.execute(sa.text("SELECT count(*) FROM knowledge_sources")).scalar_one()
    assert after == before
    assert not storage_dir.exists() or not [p for p in storage_dir.rglob("*") if p.is_file()]


def test_a_file_over_the_limit_is_rejected(
    db_url: str, sync_engine: Engine, storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PSA_UPLOAD_MAX_BYTES", "1024")
    with make_client(auth_app(db_url)) as small:
        admin, _, tag = _admin_and_tag(small, sync_engine)
        resp = _register(small, admin, [tag["id"]], data=b"x" * 5000)
    _problem(resp, 422, "file_too_large")
    assert resp.json()["detail"] == "Rejected: larger than 0.0 MB" or resp.json()[
        "detail"
    ].startswith("Rejected: larger than")
    assert not storage_dir.exists() or not [p for p in storage_dir.rglob("*") if p.is_file()]


def test_a_docx_is_accepted(client: TestClient, sync_engine: Engine) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]], name="Guide.docx", data=DOCX)
    assert source["filename"] == "Guide.docx"


# --- reads ------------------------------------------------------------------------------------


def test_the_list_filters_and_the_empty_list(client: TestClient, sync_engine: Engine) -> None:
    admin, admin_id, tag = _admin_and_tag(client, sync_engine)
    other_tag = _tag(client, admin)
    product = f"Product {uuid4().hex}"
    fresh = _registered(client, admin, [tag["id"]], product=product)
    stale = _registered(client, admin, [other_tag["id"]], product=product, title="Old guide")
    _backdate(sync_engine, stale["id"], 13)

    reader, _ = _signed_in(client, "Reader")
    _problem(client.get(BASE, headers=reader), 403)  # a role is needed to read
    _grant(sync_engine, UUID(client.get("/api/v1/me", headers=reader).json()["id"]), "commercial")

    def ids(**params: Any) -> list[str]:
        resp = client.get(BASE, headers=reader, params={"product": product, **params})
        assert resp.status_code == 200, resp.text
        assert resp.json()["stale_months"] == 12
        return [s["id"] for s in resp.json()["items"]]

    assert ids() == [stale["id"], fresh["id"]]  # longest-unreviewed first
    assert ids(stale="true") == [stale["id"]]
    assert ids(stale="false") == [fresh["id"]]
    assert ids(integration_type_id=tag["id"]) == [fresh["id"]]
    assert ids(owner_id=str(admin_id)) == [stale["id"], fresh["id"]]
    assert ids(owner_id=str(uuid4())) == []
    listed = {s["id"]: s for s in client.get(BASE, headers=reader).json()["items"]}
    assert listed[stale["id"]]["stale"] is True and listed[fresh["id"]]["stale"] is False


def test_get_returns_the_etag_and_404s(client: TestClient, sync_engine: Engine) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]])
    resp = client.get(f"{BASE}/{source['id']}", headers=admin)
    assert resp.status_code == 200 and resp.headers["ETag"] == '"1"'
    _problem(client.get(f"{BASE}/{uuid4()}", headers=admin), 404)
    _problem(client.get(f"{BASE}/not-a-uuid", headers=admin), 422)
    _problem(client.get(BASE), 401)


# --- stale and Mark reviewed --------------------------------------------------------------------


def test_stale_is_derived_and_mark_reviewed_clears_it(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]])
    _backdate(sync_engine, source["id"], 13)
    got = client.get(f"{BASE}/{source['id']}", headers=admin).json()
    assert got["stale"] is True  # row_version unchanged: the flag is derived, not stored
    assert got["row_version"] == 1

    url = f"{BASE}/{source['id']}/review"
    _problem(client.post(url, headers=admin), 428)
    _problem(client.post(url, headers=_if_match(5) | admin), 412)
    resp = client.post(url, headers={**admin, **_if_match(1)})
    assert resp.status_code == 200, resp.text
    reviewed = resp.json()
    assert reviewed["stale"] is False and reviewed["row_version"] == 2
    assert reviewed["last_reviewed_on"] == datetime.now(UTC).date().isoformat()
    assert resp.headers["ETag"] == '"2"'
    assert [e["event_type"] for e in _events(sync_engine, source["id"])] == [
        "knowledge.source.registered",
        "knowledge.source.reviewed",
    ]
    assert _events(sync_engine, source["id"])[-1]["payload"] == {"was_stale": True}


def test_exactly_twelve_months_is_not_stale_but_older_is(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]])
    today = datetime.now(UTC).date()
    for days, stale in ((364, False), (400, True)):
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE knowledge_sources SET last_reviewed_on = :d WHERE id = :s"),
                {"d": today - timedelta(days=days), "s": source["id"]},
            )
        assert client.get(f"{BASE}/{source['id']}", headers=admin).json()["stale"] is stale


# --- ownership --------------------------------------------------------------------------------


def test_only_an_administrator_or_the_owner_writes(client: TestClient, sync_engine: Engine) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    owner, owner_id = _expert(client, sync_engine, "Owner Expert")
    source = _registered(client, admin, [tag["id"]], owner_id=owner_id)
    stranger, _ = _expert(client, sync_engine, "Stranger Expert")
    url = f"{BASE}/{source['id']}"
    headers = {**stranger, **_if_match(1)}

    _problem(client.patch(url, headers=headers, json={"title": "Hijacked"}), 403)
    _problem(client.post(f"{url}/review", headers=headers), 403)
    _problem(client.post(f"{url}/retire", headers=headers, json={"reason": "x"}), 403)
    _problem(client.post(f"{url}/parse", headers=stranger), 403)
    _problem(
        client.post(
            f"{url}/versions",
            headers=headers,
            params={"product_version": "3"},
            files={"file": ("a.md", _text_file(), "text/markdown")},
        ),
        403,
    )
    assert client.get(url, headers=stranger).json()["title"] == "Install guide"  # reads are open

    assert client.post(f"{url}/review", headers={**owner, **_if_match(1)}).status_code == 200
    assert client.post(f"{url}/review", headers={**admin, **_if_match(2)}).status_code == 200


# --- retag / edit -----------------------------------------------------------------------------


def test_retag_replaces_the_tags_and_traces_the_change(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    other = _tag(client, admin)
    source = _registered(client, admin, [tag["id"]])
    url = f"{BASE}/{source['id']}"

    _problem(client.patch(url, json={"title": "x"}, headers=admin), 428)
    _problem(client.patch(url, json={"title": "x"}, headers={**admin, **_if_match(9)}), 412)
    _problem(
        client.patch(url, json={"integration_type_ids": []}, headers={**admin, **_if_match(1)}),
        422,
    )
    resp = client.patch(
        url,
        headers={**admin, **_if_match(1)},
        json={"integration_type_ids": [other["id"]], "product": " EDI ", "title": "New title"},
    )
    assert resp.status_code == 200, resp.text
    changed = resp.json()
    assert [t["id"] for t in changed["integration_types"]] == [other["id"]]
    assert (changed["product"], changed["title"], changed["row_version"]) == ("EDI", "New title", 2)
    event = _events(sync_engine, source["id"])[-1]
    assert event["event_type"] == "knowledge.source.retagged"
    assert event["payload"] == {
        "tag_ids_added": [other["id"]],
        "tag_ids_removed": [tag["id"]],
        "product_changed": True,
        "title_changed": True,
        "owner_changed": False,
    }

    # Nothing changed: 200, nothing written.
    same = client.patch(url, headers={**admin, **_if_match(2)}, json={"title": "New title"})
    assert same.status_code == 200 and same.json()["row_version"] == 2
    assert len(_events(sync_engine, source["id"])) == 2


def test_an_existing_retired_tag_stays_but_cannot_be_added(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    gone = _tag(client, admin)
    source = _registered(client, admin, [tag["id"], gone["id"]])
    client.post(
        f"{CATALOGUE}/{gone['id']}/retire",
        headers={**admin, **_if_match(gone["row_version"])},
        json={"reason": "obsolete"},
    )
    shown = client.get(f"{BASE}/{source['id']}", headers=admin).json()
    assert {t["id"]: t["retired"] for t in shown["integration_types"]} == {
        tag["id"]: False,
        gone["id"]: True,
    }  # existing references keep resolving, shown as Retired
    # Retitling with the same tags (retired one kept) is fine.
    ok = client.patch(
        f"{BASE}/{source['id']}",
        headers={**admin, **_if_match(1)},
        json={"integration_type_ids": [tag["id"], gone["id"]]},
    )
    assert ok.status_code == 200
    fresh = _registered(client, admin, [tag["id"]])
    _problem(
        client.patch(
            f"{BASE}/{fresh['id']}",
            headers={**admin, **_if_match(1)},
            json={"integration_type_ids": [gone["id"]]},
        ),
        422,
    )


def test_only_an_administrator_changes_the_owner(client: TestClient, sync_engine: Engine) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    owner, owner_id = _expert(client, sync_engine, "Owner Expert")
    _, new_owner = _expert(client, sync_engine, "Next Owner")
    source = _registered(client, admin, [tag["id"]], owner_id=owner_id)
    url = f"{BASE}/{source['id']}"
    _problem(
        client.patch(url, headers={**owner, **_if_match(1)}, json={"owner_id": str(new_owner)}),
        403,
    )
    resp = client.patch(url, headers={**admin, **_if_match(1)}, json={"owner_id": str(new_owner)})
    assert resp.status_code == 200 and resp.json()["owner"]["id"] == str(new_owner)
    assert _events(sync_engine, source["id"])[-1]["payload"]["owner_changed"] is True


def test_owner_candidates_are_for_administrators(client: TestClient, sync_engine: Engine) -> None:
    admin, _, _ = _admin_and_tag(client, sync_engine)
    name = f"Zebra {uuid4().hex}"
    expert, _ = _expert(client, sync_engine, name)
    found = client.get(f"{BASE}/owner-candidates", headers=admin, params={"q": name})
    assert found.status_code == 200
    assert [u["name"] for u in found.json()["items"]] == [name]
    _problem(client.get(f"{BASE}/owner-candidates", headers=expert, params={"q": "Zebra"}), 403)


# --- versions ---------------------------------------------------------------------------------


def test_a_new_version_keeps_the_old_one_readable_and_is_traced(
    client: TestClient, sync_engine: Engine, storage_dir: Path, db_url: str
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    first = _text_file("one")
    source = _registered(client, admin, [tag["id"]], data=first)
    second = _text_file("two")
    url = f"{BASE}/{source['id']}"

    def upload(headers: dict[str, str], **kw: Any) -> Response:
        return client.post(
            f"{url}/versions",
            headers=headers,
            params={"product_version": "2.2"},
            files={"file": (kw.get("name", "guide-v2.md"), kw.get("data", second), "text/plain")},
        )

    _problem(upload(admin), 428)
    _problem(upload({**admin, **_if_match(7)}), 412)
    bad = upload({**admin, **_if_match(1)}, name="guide.exe", data=b"MZ")
    assert bad.status_code == 422 and bad.json()["code"] == "file_type_not_allowed"
    resp = upload({**admin, **_if_match(1)})
    assert resp.status_code == 201, resp.text
    updated = resp.json()
    assert (updated["version"], updated["version_count"], updated["row_version"]) == (2, 2, 2)
    assert (updated["product_version"], updated["filename"]) == ("2.2", "guide-v2.md")
    assert updated["parse"]["status"] == "queued"

    versions = client.get(f"{url}/versions", headers=admin).json()["items"]
    assert [(v["version"], v["product_version"], v["filename"]) for v in versions] == [
        (2, "2.2", "guide-v2.md"),
        (1, "2.1", "guide.md"),
    ]
    assert len(_jobs(sync_engine, source["id"])) == 2
    event = _events(sync_engine, source["id"])[-1]
    assert event["event_type"] == "knowledge.source.version_added"
    assert event["payload"] == {"from_version": 1, "to_version": 2, "size_bytes": len(second)}

    # The earlier version's original file is still downloadable, through a signed link.
    link = client.post(f"{url}/versions/1/download-link", headers=admin)
    assert link.status_code == 200, link.text
    got = client.get(link.json()["url"])  # the token is the credential: no auth header
    assert got.status_code == 200 and got.content == first
    assert "attachment" in got.headers["content-disposition"]
    assert got.headers["x-content-type-options"] == "nosniff"
    _problem(client.post(f"{url}/versions/9/download-link", headers=admin), 404)
    tampered = link.json()["url"][:-3] + "AAA"
    _problem(client.get(tampered), 403)

    # And the text of both versions after parsing.
    assert _drain(db_url) == ["succeeded", "succeeded"]
    text1 = client.get(f"{url}/versions/1/text", headers=admin).json()
    assert text1["text"] == first.decode() and text1["char_count"] == len(first.decode())
    assert client.get(f"{url}/versions/2/text", headers=admin).json()["text"] == second.decode()


# --- retire -----------------------------------------------------------------------------------


def test_retire_keeps_the_source_readable_and_blocks_writes(
    client: TestClient, sync_engine: Engine
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]])
    url = f"{BASE}/{source['id']}"
    _problem(
        client.post(f"{url}/retire", headers={**admin, **_if_match(1)}, json={"reason": " "}), 422
    )
    resp = client.post(
        f"{url}/retire", headers={**admin, **_if_match(1)}, json={"reason": "Superseded"}
    )
    assert resp.status_code == 200, resp.text
    retired = resp.json()
    assert (retired["retired"], retired["status"], retired["retired_reason"]) == (
        True,
        "retired",
        "Superseded",
    )
    assert _events(sync_engine, source["id"])[-1]["event_type"] == "knowledge.source.retired"
    assert _events(sync_engine, source["id"])[-1]["payload"] == {"version": 1}

    again = client.post(
        f"{url}/retire", headers={**admin, **_if_match(2)}, json={"reason": "Again"}
    )
    assert again.status_code == 200 and again.json()["row_version"] == 2  # no-op
    _problem(client.post(f"{url}/review", headers={**admin, **_if_match(2)}), 409)
    _problem(
        client.patch(url, headers={**admin, **_if_match(2)}, json={"title": "No"}),
        409,
    )
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(f"{url}/versions", headers=admin).status_code == 200
    listed = [s["id"] for s in client.get(BASE, headers=admin).json()["items"]]
    assert source["id"] not in listed
    with_retired = client.get(BASE, headers=admin, params={"include_retired": "true"}).json()
    assert source["id"] in [s["id"] for s in with_retired["items"]]


# --- parse job --------------------------------------------------------------------------------


def test_a_parse_job_stores_the_text_and_traces(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    data = _text_file("parse")
    source = _registered(client, admin, [tag["id"]], data=data)

    assert _drain(db_url) == ["succeeded"]

    row = _parse_row(sync_engine, source["id"])
    assert (row["status"], row["error_code"]) == ("parsed", None)
    assert row["parser"] == "markdown@1" and row["char_count"] == len(data.decode())
    sha = row["text_sha256"]
    assert (storage_dir / "sha256" / sha[:2] / sha[2:4] / sha).read_bytes() == data
    parsed = [e for e in _events(sync_engine, source["id"]) if e["event_type"].endswith(".parsed")]
    (event,) = parsed
    assert event["payload"] == {"version": 1, "char_count": len(data.decode())}
    assert (event["actor_type"], event["actor_id"]) == ("system", JOB_TYPE)
    assert event["opportunity_id"] is None
    assert client.get(f"{BASE}/{source['id']}", headers=admin).json()["parse"] == {
        "status": "parsed",
        "error_code": None,
    }
    assert _drain(db_url) == []  # nothing left, and a repeat run would do nothing


@pytest.mark.parametrize(
    ("name", "code"), [("corrupt.pdf", "unreadable"), ("scanned.pdf", "no_text")]
)
def test_a_corrupt_file_fails_alone_and_can_be_retried(
    client: TestClient, sync_engine: Engine, db_url: str, name: str, code: str
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    bad = _registered(client, admin, [tag["id"]], name=name, data=(FIXTURES / name).read_bytes())
    good = _registered(client, admin, [tag["id"]])

    assert _drain(db_url) == ["succeeded", "succeeded"]

    failed = client.get(f"{BASE}/{bad['id']}", headers=admin).json()
    assert failed["parse"] == {"status": "failed", "error_code": code}
    assert client.get(f"{BASE}/{good['id']}", headers=admin).json()["parse"]["status"] == "parsed"
    _problem(client.get(f"{BASE}/{bad['id']}/versions/1/text", headers=admin), 404)

    _problem(client.post(f"{BASE}/{good['id']}/parse", headers=admin), 409, "parse_not_failed")
    resp = client.post(f"{BASE}/{bad['id']}/parse", headers=admin)
    assert resp.status_code == 202, resp.text
    assert resp.json()["parse"] == {"status": "queued", "error_code": None}
    retried = _events(sync_engine, bad["id"])[-1]
    assert retried["event_type"] == "knowledge.source.parse_retried"
    assert retried["payload"] == {"version": 1, "error_code": code}
    assert len(_jobs(sync_engine, bad["id"])) == 2
    assert _drain(db_url) == ["succeeded"]
    assert client.get(f"{BASE}/{bad['id']}", headers=admin).json()["parse"]["status"] == "failed"


def test_the_worker_loads_the_knowledge_parse_job() -> None:
    from app import main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    assert JOB_TYPE in REGISTRY and REGISTRY[JOB_TYPE].priority == "interactive"


# --- parse job attempts and download-link edges -----------------------------------------------


def _parse_state(client: TestClient, admin: dict[str, str], source_id: str) -> dict[str, Any]:
    return client.get(f"{BASE}/{source_id}", headers=admin).json()["parse"]  # type: ignore[no-any-return]


def _run_parse_attempt(db_url: str, source_id: str, attempt: int) -> type[BaseException] | None:
    async def scenario() -> type[BaseException] | None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = knowledge_jobs.JobContext(
            job_id=uuid4(),
            job_type=JOB_TYPE,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=None,
            engine=engine,
        )
        try:
            await knowledge_jobs.parse_source(
                ctx, knowledge_jobs.ParseKnowledgeSource(source_id=UUID(source_id), version=1)
            )
        except Exception as exc:
            return type(exc)
        finally:
            await engine.dispose()
        return None

    return run_async(scenario())


def test_a_timed_out_parse_retries_and_fails_only_on_the_final_attempt(
    client: TestClient,
    sync_engine: Engine,
    storage_dir: Path,
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def times_out(*args: Any, **kwargs: Any) -> Any:
        raise ParseTimeoutError(60.0)

    monkeypatch.setattr(knowledge_jobs.parse_runner, "run_parse", times_out)
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]])

    assert _run_parse_attempt(db_url, source["id"], 1) is ParseTimeoutError
    assert _parse_state(client, admin, source["id"])["status"] == "parsing"  # retried, not failed
    assert _run_parse_attempt(db_url, source["id"], 2) is ParseTimeoutError
    assert _parse_state(client, admin, source["id"]) == {
        "status": "failed",
        "error_code": "timeout",
    }


def test_a_missing_stored_file_is_retried_then_reported_unreadable(
    client: TestClient, sync_engine: Engine, storage_dir: Path, db_url: str
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]], data=_text_file("gone"))
    for blob in storage_dir.rglob("*"):
        if blob.is_file():
            blob.unlink()

    assert _run_parse_attempt(db_url, source["id"], 1) is knowledge_jobs.BlobMissingError
    assert _parse_state(client, admin, source["id"])["status"] == "parsing"
    assert _run_parse_attempt(db_url, source["id"], 2) is knowledge_jobs.BlobMissingError
    assert _parse_state(client, admin, source["id"]) == {
        "status": "failed",
        "error_code": "unreadable",
    }


def test_an_expired_or_malformed_link_is_403_and_a_vanished_file_is_404(
    client: TestClient, sync_engine: Engine, storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, _, tag = _admin_and_tag(client, sync_engine)
    source = _registered(client, admin, [tag["id"]], data=_text_file("link"))
    url = f"{BASE}/{source['id']}/versions/1/download-link"
    link = client.post(url, headers=admin).json()["url"]

    monkeypatch.setattr("app.platform.downloads.time.time", lambda: 4_000_000_000.0)
    _problem(client.get(link), 403)  # expired
    monkeypatch.undo()
    _problem(client.get("/api/v1/downloads/caf%C3%A9.%C3%A9"), 403)  # non-ASCII, not a 500
    _problem(client.get("/api/v1/downloads/not-a-token"), 403)

    fresh = client.post(url, headers=admin).json()["url"]
    for blob in storage_dir.rglob("*"):
        if blob.is_file():
            blob.unlink()
    _problem(client.get(fresh), 404)


def test_prod_refuses_the_local_download_signing_key() -> None:
    with pytest.raises(ValueError, match="download_signing_key"):
        Settings(env="prod")
    assert Settings(env="prod", download_signing_key="a-real-secret-value").env == "prod"
