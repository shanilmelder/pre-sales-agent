"""Opportunity Sources (Story 2.1 Parts A and B) against a real, migrated Postgres as psa_app.

Covers the spec's I/O matrix: upload, sales representative, reader only, non-reader, bad
type, spoofed content, too large, empty, same bytes (next version), same name (new
Source), and the list; plus the trace, `ref_count`, `can_add_sources` and the
Opportunity's untouched `row_version`. Files go to a temp `PSA_STORAGE_DIR`.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request

from app.modules.identity.application.public import Principal, Role
from app.modules.intake.api.routes import _content_length
from app.modules.intake.application import public as intake
from app.platform.actor import Actor
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.errors import FileTooLargeError
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_intake_filetypes import DOCX, OLE, PNG
from tests.test_opportunities import PSE, _add, _create, _user

BASE = "/api/v1/opportunities"
MB = 1024 * 1024


def vtt() -> bytes:
    """A transcript; unique per call, since `platform_files` is shared across tests."""
    return f"WEBVTT\n\nNOTE {uuid4()}\n\n00:00.000 --> 00:02.000\n[CUSTOMER]: 40 ports\n".encode()


def pdf() -> bytes:
    """A PDF header; unique per call."""
    return f"%PDF-1.7\n% {uuid4()}\n1 0 obj << /Type /Catalog >> endobj\n".encode()


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(root))
    return root


@pytest.fixture
def client(db_url: str, storage_dir: Path) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _sources_url(opportunity_id: str) -> str:
    return f"{BASE}/{opportunity_id}/sources"


def _upload(
    client: TestClient, headers: dict[str, str], opportunity_id: str, name: str, data: bytes
) -> Any:
    return client.post(
        _sources_url(opportunity_id),
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
    )


def _events(engine: Engine, opportunity_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
                    "AND event_type LIKE 'intake.%' ORDER BY occurred_at, id"
                ),
                {"o": opportunity_id},
            ).mappings()
        ]


def _ref_count(engine: Engine, sha256: str) -> int | None:
    with engine.connect() as conn:
        value: int | None = conn.execute(
            sa.text("SELECT ref_count FROM platform_files WHERE sha256 = :s"), {"s": sha256}
        ).scalar_one_or_none()
    return value


def _source_count(engine: Engine, opportunity_id: str) -> int:
    with engine.connect() as conn:
        count: int = conn.execute(
            sa.text("SELECT count(*) FROM intake_sources WHERE opportunity_id = :o"),
            {"o": opportunity_id},
        ).scalar_one()
    return count


def _stored_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _owner_and_opportunity(client: TestClient, engine: Engine) -> tuple[dict[str, str], Any]:
    headers, _ = _user(client, engine, "Owner Person", PSE)
    return headers, _create(client, headers)


def _assert_nothing_stored(engine: Engine, storage_dir: Path, opportunity_id: str) -> None:
    assert _source_count(engine, opportunity_id) == 0
    assert _events(engine, opportunity_id) == []
    assert _stored_files(storage_dir) == []


# --- upload ---------------------------------------------------------------------------------


def test_collaborator_uploads_a_transcript(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    owner_headers, opp = _owner_and_opportunity(client, sync_engine)
    member_headers, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    opp = _add(client, owner_headers, opp, member_id).json()

    data = vtt()
    resp = _upload(client, member_headers, opp["id"], "call.vtt", data)

    assert resp.status_code == 201, resp.text
    source = resp.json()
    assert UUID(source["id"]).version == 7
    assert source["kind"] == "transcript"
    assert source["filename"] == "call.vtt"
    assert (source["version"], source["version_count"]) == (1, 1)
    assert source["size_bytes"] == len(data)
    assert source["uploaded_by"] == {"id": str(member_id), "name": "Member Person"}
    assert source["uploaded_at"].endswith("Z")

    sha = _sha(data)
    assert BlobStore(storage_dir).path_for(sha).read_bytes() == data
    assert _ref_count(sync_engine, sha) == 1
    assert not list((storage_dir / "tmp").iterdir())

    (event,) = _events(sync_engine, opp["id"])
    assert event["event_type"] == "intake.source.added"
    assert event["payload"] == {"version": 1, "kind": "transcript", "size_bytes": len(data)}
    assert (event["subject_type"], str(event["subject_id"])) == ("intake.source", source["id"])
    assert event["subject_version"] == 1
    assert (event["actor_type"], event["actor_id"]) == ("user", str(member_id))
    assert "call.vtt" not in str(event) and "[CUSTOMER]" not in str(event)

    # Adding a Source never bumps the Opportunity's version.
    after = client.get(f"{BASE}/{opp['id']}", headers=owner_headers)
    assert after.json()["row_version"] == opp["row_version"]


def test_sales_representative_collaborator_uploads_a_pdf(
    client: TestClient, sync_engine: Engine
) -> None:
    owner_headers, opp = _owner_and_opportunity(client, sync_engine)
    rep_headers, rep_id = _user(client, sync_engine, "Sales Rep", "sales_representative")
    _add(client, owner_headers, opp, rep_id)

    resp = _upload(client, rep_headers, opp["id"], "rfp.pdf", pdf())

    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "document"


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [
        ("mail.eml", b"From: x\r\nSubject: y\r\n\r\nbody\r\n", "email"),
        ("mail.MSG", OLE, "email"),
        ("notes.txt", "Größe\n".encode(), "note"),
        ("spec.docx", DOCX, "document"),
    ],
)
def test_owner_uploads_every_allowed_kind(
    client: TestClient, sync_engine: Engine, name: str, data: bytes, kind: str
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    resp = _upload(client, headers, opp["id"], name, data)
    assert resp.status_code == 201, resp.text
    assert (resp.json()["kind"], resp.json()["filename"]) == (kind, name)


def test_filename_is_stored_without_path_components(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    resp = _upload(client, headers, opp["id"], "  C:\\Users\\me\\notes.txt ", b"hello")
    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "notes.txt"


# --- who ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["head_of_delivery", "platform_administrator"])
def test_reader_who_is_not_a_collaborator_gets_403(
    client: TestClient, sync_engine: Engine, storage_dir: Path, role: str
) -> None:
    _, opp = _owner_and_opportunity(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Reader", role)

    resp = _upload(client, reader, opp["id"], "call.vtt", vtt())

    assert resp.status_code == 403, resp.text
    assert_problem(resp.json(), 403, "forbidden")
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])
    # They still see the list.
    assert client.get(_sources_url(opp["id"]), headers=reader).status_code == 200


@pytest.mark.parametrize("role", ["presales_engineer", "sales_representative", None])
def test_non_reader_and_unknown_opportunity_get_404(
    client: TestClient, sync_engine: Engine, storage_dir: Path, role: str | None
) -> None:
    _, opp = _owner_and_opportunity(client, sync_engine)
    other, _ = _user(client, sync_engine, "Outsider", *([role] if role else []))

    hidden = _upload(client, other, opp["id"], "call.vtt", vtt())
    unknown = _upload(client, other, str(uuid4()), "call.vtt", vtt())
    listed = client.get(_sources_url(opp["id"]), headers=other)

    for resp in (hidden, unknown, listed):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
    assert hidden.json()["detail"] == unknown.json()["detail"]
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_can_add_sources_on_the_read_model(client: TestClient, sync_engine: Engine) -> None:
    owner_headers, opp = _owner_and_opportunity(client, sync_engine)
    member_headers, member_id = _user(client, sync_engine, "Member", "sales_representative")
    _add(client, owner_headers, opp, member_id)
    hod, _ = _user(client, sync_engine, "HoD", "head_of_delivery")

    def can_add(headers: dict[str, str]) -> bool:
        flag: bool = client.get(f"{BASE}/{opp['id']}", headers=headers).json()["can_add_sources"]
        return flag

    assert can_add(owner_headers) is True
    assert can_add(member_headers) is True
    assert can_add(hod) is False


# --- rejections -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data", "code", "detail"),
    [
        (
            "setup.exe",
            b"MZ\x90\x00",
            "file_type_not_allowed",
            "Rejected: .exe files aren't allowed",
        ),
        ("SETUP.EXE", b"MZ", "file_type_not_allowed", "Rejected: .exe files aren't allowed"),
        ("image.pdf", PNG, "file_content_mismatch", "Rejected: the content doesn't match .pdf"),
        ("spec.docx", pdf(), "file_content_mismatch", "Rejected: the content doesn't match .docx"),
        (
            "notes.txt",
            b"bad\x00text",
            "file_content_mismatch",
            "Rejected: the content doesn't match .txt",
        ),
        ("empty.txt", b"", "file_empty", "Rejected: the file is empty"),
    ],
)
def test_rejected_files_store_nothing(
    client: TestClient,
    sync_engine: Engine,
    storage_dir: Path,
    name: str,
    data: bytes,
    code: str,
    detail: str,
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)

    resp = _upload(client, headers, opp["id"], name, data)

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert_problem(body, 422, code)
    assert body["detail"] == detail
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])
    if data:
        assert _ref_count(sync_engine, _sha(data)) is None


def test_larger_than_50_mb_is_rejected_and_leaves_no_temp_file(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    data = b"%PDF-" + b"0" * (50 * MB + 1 - 5)

    resp = _upload(client, headers, opp["id"], "big.pdf", data)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "file_too_large")
    assert resp.json()["detail"] == "Rejected: larger than 50 MB"
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_exactly_50_mb_is_accepted(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    data = b"%PDF-" + b"0" * (50 * MB - 5)

    resp = _upload(client, headers, opp["id"], "big.pdf", data)

    assert resp.status_code == 201, resp.text
    assert resp.json()["size_bytes"] == 50 * MB


def test_body_without_a_file_part_is_422(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    for resp in (
        client.post(_sources_url(opp["id"]), headers=headers, data={"file": "not a file"}),
        client.post(_sources_url(opp["id"]), headers=headers, json={"file": "x"}),
    ):
        assert resp.status_code == 422, resp.text
        assert_problem(resp.json(), 422, "validation_error")
        assert resp.json()["detail"] == "Invalid fields: body.file"


def test_oversized_content_length_is_rejected_before_reading(
    db_url: str, sync_engine: Engine, client: TestClient, storage_dir: Path
) -> None:
    """A declared length past the limit is answered without reading a byte of the body."""
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp_id = _create(client, headers)["id"]
    owner = Principal(Actor("user", str(owner_id)), frozenset({Role.PRESALES_ENGINEER}))

    class Untouchable:
        async def filename(self) -> str:
            raise AssertionError("the body was read")

        async def chunks(self) -> AsyncIterator[bytes]:
            raise AssertionError("the body was read")
            yield b""  # pragma: no cover

    async def attempt() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake.add_file(
                    uow,
                    owner,
                    UUID(opp_id),
                    Untouchable(),
                    store=BlobStore(storage_dir),
                    max_bytes=MB,
                    content_length=intake.max_body_bytes(MB) + 1,
                )
        finally:
            await engine.dispose()

    with pytest.raises(FileTooLargeError) as caught:
        run_async(attempt())
    assert caught.value.detail == "Rejected: larger than 1 MB"
    _assert_nothing_stored(sync_engine, storage_dir, opp_id)


# --- versions -------------------------------------------------------------------------------


def test_same_bytes_become_the_next_version_of_the_same_source(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    data = vtt()
    first = _upload(client, headers, opp["id"], "call.vtt", data).json()

    resp = _upload(client, headers, opp["id"], "renamed-call.VTT", data)

    assert resp.status_code == 201, resp.text
    second = resp.json()
    assert second["id"] == first["id"]
    assert (second["version"], second["version_count"]) == (2, 2)
    assert second["filename"] == "renamed-call.VTT"
    assert _source_count(sync_engine, opp["id"]) == 1
    assert _ref_count(sync_engine, _sha(data)) == 2
    blobs = [p for p in _stored_files(storage_dir) if "sha256" in p.parts]
    assert blobs == [BlobStore(storage_dir).path_for(_sha(data))]
    events = _events(sync_engine, opp["id"])
    assert [e["payload"]["version"] for e in events] == [1, 2]
    assert {str(e["subject_id"]) for e in events} == {first["id"]}
    assert events[1]["subject_version"] == 2


def test_same_bytes_in_another_opportunity_are_a_new_source_sharing_the_blob(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    other = _create(client, headers)
    data = f"unique {uuid4()}".encode()

    a = _upload(client, headers, opp["id"], "notes.txt", data).json()
    b = _upload(client, headers, other["id"], "notes.txt", data).json()

    assert a["id"] != b["id"]
    assert b["version"] == 1
    assert _ref_count(sync_engine, _sha(data)) == 2


def test_same_name_with_different_bytes_is_a_new_source(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    draft = f"second draft {uuid4()}".encode()
    first = _upload(client, headers, opp["id"], "notes.txt", f"first {uuid4()}".encode()).json()

    second = _upload(client, headers, opp["id"], "notes.txt", draft).json()

    assert second["id"] != first["id"]
    assert second["version"] == 1
    assert _source_count(sync_engine, opp["id"]) == 2
    assert _ref_count(sync_engine, _sha(draft)) == 1
    assert len([p for p in _stored_files(storage_dir) if "sha256" in p.parts]) == 2


# --- list -----------------------------------------------------------------------------------


@pytest.mark.parametrize("reader", ["owner", "collaborator", "head_of_delivery", "admin"])
def test_readers_list_sources_newest_first_with_latest_version(
    client: TestClient, sync_engine: Engine, reader: str
) -> None:
    owner_headers, opp = _owner_and_opportunity(client, sync_engine)
    member_headers, member_id = _user(client, sync_engine, "Member Person", "commercial")
    _add(client, owner_headers, opp, member_id)
    data = vtt()
    first = _upload(client, owner_headers, opp["id"], "call.vtt", data).json()
    second = _upload(client, member_headers, opp["id"], "rfp.pdf", pdf()).json()
    _upload(client, member_headers, opp["id"], "call-again.vtt", data)
    headers = {
        "owner": owner_headers,
        "collaborator": member_headers,
        "head_of_delivery": _user(client, sync_engine, "HoD", "head_of_delivery")[0],
        "admin": _user(client, sync_engine, "Admin", "platform_administrator")[0],
    }[reader]

    resp = client.get(_sources_url(opp["id"]), headers=headers)

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["id"] for i in items] == [second["id"], first["id"]]
    latest = items[1]
    assert (latest["version"], latest["version_count"]) == (2, 2)
    assert latest["filename"] == "call-again.vtt"
    assert latest["uploaded_by"] == {"id": str(member_id), "name": "Member Person"}
    assert latest["kind"] == "transcript"


def test_empty_list(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    resp = client.get(_sources_url(opp["id"]), headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


# --- request edge cases ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("123", 123), (" 42 ", 42), ("²", None), ("¹²", None), ("-1", None), ("", None), (None, None)],
)
def test_content_length_header_parsing(raw: str | None, expected: int | None) -> None:
    """Only ASCII digits count: "²" passes `str.isdigit()` but `int()` rejects it."""
    headers = [] if raw is None else [(b"content-length", raw.encode("latin-1"))]
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": headers})
    assert _content_length(request) == expected


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("invoice‮fdp.txt", "Rejected: the file name isn't valid"),
        ("notes\u0085.txt", "Rejected: the file name isn't valid"),
        ("x" * 256 + ".txt", "Rejected: the file name is longer than 255 characters"),
    ],
)
def test_unusable_filenames_are_422_and_store_nothing(
    client: TestClient, sync_engine: Engine, storage_dir: Path, name: str, detail: str
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)

    resp = _upload(client, headers, opp["id"], name, b"hello")

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert resp.json()["detail"] == detail
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_large_non_file_part_before_the_file_hits_the_body_cap(
    db_url: str, sync_engine: Engine, storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streamed without Content-Length, so only the cap on the body read can stop it."""
    monkeypatch.setenv("PSA_UPLOAD_MAX_BYTES", str(MB))
    boundary = "psa-cap-test"
    junk = b"j" * (intake.max_body_bytes(MB) + 1)
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="junk"\r\n\r\n'.encode()
        + junk
        + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="notes.txt"\r\n\r\nhello\r\n--{boundary}--\r\n'.encode()
    )

    def chunked() -> Iterator[bytes]:
        for i in range(0, len(body), 64 * 1024):
            yield body[i : i + 64 * 1024]

    with make_client(auth_app(db_url)) as client:
        headers, opp = _owner_and_opportunity(client, sync_engine)
        resp = client.post(
            _sources_url(opp["id"]),
            headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            content=chunked(),
        )

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "file_too_large")
    assert resp.json()["detail"] == "Rejected: larger than 1 MB"
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


# --- concurrency ----------------------------------------------------------------------------


def test_concurrent_identical_uploads_become_versions_of_one_source(
    db_url: str, sync_engine: Engine, client: TestClient, storage_dir: Path
) -> None:
    """The second upload waits for the first's uncommitted transaction, then becomes v2."""
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp_id = UUID(_create(client, headers)["id"])
    owner = Principal(Actor("user", str(owner_id)), frozenset({Role.PRESALES_ENGINEER}))
    data = vtt()

    class Incoming:
        async def filename(self) -> str:
            return "call.vtt"

        async def chunks(self) -> AsyncIterator[bytes]:
            yield data

    async def scenario() -> tuple[bool, list[Any]]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        added = asyncio.Event()
        release = asyncio.Event()

        async def add(uow: Any) -> Any:
            return await intake.add_file(
                uow, owner, opp_id, Incoming(), store=BlobStore(storage_dir), max_bytes=MB
            )

        async def first() -> Any:
            async with unit_of_work(engine) as uow:
                source = await add(uow)
                added.set()
                await release.wait()  # hold the content lock, uncommitted
                return source

        async def second() -> Any:
            await added.wait()
            async with unit_of_work(engine) as uow:
                return await add(uow)

        try:
            t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
            await added.wait()
            await asyncio.sleep(0.5)
            second_blocked = not t2.done()
            release.set()
            return second_blocked, await asyncio.gather(t1, t2, return_exceptions=True)
        finally:
            await engine.dispose()

    second_blocked, (a, b) = run_async(scenario())

    assert second_blocked
    assert not isinstance(a, BaseException), a
    assert not isinstance(b, BaseException), b
    assert a.id == b.id
    assert (a.version, b.version) == (1, 2)
    assert _source_count(sync_engine, str(opp_id)) == 1
    assert _ref_count(sync_engine, _sha(data)) == 2
    assert [e["payload"]["version"] for e in _events(sync_engine, str(opp_id))] == [1, 2]


# --- pasted text (Part B) -------------------------------------------------------------------


def _text_url(opportunity_id: str) -> str:
    return f"{_sources_url(opportunity_id)}/text"


def _paste(client: TestClient, headers: dict[str, str], opportunity_id: str, text: Any) -> Any:
    return client.post(_text_url(opportunity_id), headers=headers, json={"text": text})


def test_collaborator_pastes_text_as_a_note(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    owner_headers, opp = _owner_and_opportunity(client, sync_engine)
    member_headers, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    opp = _add(client, owner_headers, opp, member_id).json()
    note = f"Customer needs SAP sync {uuid4()}"

    resp = _paste(client, member_headers, opp["id"], f"  {note}\n")

    assert resp.status_code == 201, resp.text
    source = resp.json()
    assert (source["kind"], source["filename"]) == ("note", "Pasted text")
    assert (source["version"], source["version_count"]) == (1, 1)
    data = note.encode()
    assert source["size_bytes"] == len(data)
    assert source["uploaded_by"] == {"id": str(member_id), "name": "Member Person"}

    sha = _sha(data)
    assert BlobStore(storage_dir).path_for(sha).read_bytes() == data
    assert _ref_count(sync_engine, sha) == 1
    assert not list((storage_dir / "tmp").iterdir())

    (event,) = _events(sync_engine, opp["id"])
    assert event["event_type"] == "intake.source.added"
    assert event["payload"] == {"version": 1, "kind": "note", "size_bytes": len(data)}
    assert (event["subject_type"], str(event["subject_id"])) == ("intake.source", source["id"])
    assert "SAP" not in str(event)

    after = client.get(f"{BASE}/{opp['id']}", headers=owner_headers)
    assert after.json()["row_version"] == opp["row_version"]
    listed = client.get(_sources_url(opp["id"]), headers=owner_headers).json()["items"]
    assert [i["id"] for i in listed] == [source["id"]]


def test_sales_representative_collaborator_pastes_text(
    client: TestClient, sync_engine: Engine
) -> None:
    owner_headers, opp = _owner_and_opportunity(client, sync_engine)
    rep_headers, rep_id = _user(client, sync_engine, "Sales Rep", "sales_representative")
    _add(client, owner_headers, opp, rep_id)

    resp = _paste(client, rep_headers, opp["id"], f"call note {uuid4()}")

    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("role", ["head_of_delivery", "platform_administrator"])
def test_reader_who_is_not_a_collaborator_cannot_paste(
    client: TestClient, sync_engine: Engine, storage_dir: Path, role: str
) -> None:
    _, opp = _owner_and_opportunity(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Reader", role)

    resp = _paste(client, reader, opp["id"], f"note {uuid4()}")

    assert resp.status_code == 403, resp.text
    assert_problem(resp.json(), 403, "forbidden")
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


@pytest.mark.parametrize("role", ["presales_engineer", "sales_representative", None])
def test_non_reader_and_unknown_opportunity_paste_get_404(
    client: TestClient, sync_engine: Engine, storage_dir: Path, role: str | None
) -> None:
    _, opp = _owner_and_opportunity(client, sync_engine)
    other, _ = _user(client, sync_engine, "Outsider", *([role] if role else []))

    hidden = _paste(client, other, opp["id"], f"note {uuid4()}")
    unknown = _paste(client, other, str(uuid4()), f"note {uuid4()}")

    for resp in (hidden, unknown):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
    assert hidden.json()["detail"] == unknown.json()["detail"]
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


@pytest.mark.parametrize(
    ("text", "code", "detail"),
    [
        ("   \n\t", "file_empty", "Rejected: the text is empty"),
        ("", "file_empty", "Rejected: the text is empty"),
        ("x" * 1_000_001, "file_too_large", "Rejected: longer than 1,000,000 characters"),
        (
            "  " + "x" * 1_000_001 + "  ",
            "file_too_large",
            "Rejected: longer than 1,000,000 characters",
        ),
        (
            "bad\x00text",
            "file_content_mismatch",
            "Rejected: the text contains unsupported characters",
        ),
    ],
    ids=["blank", "empty", "too-long", "too-long-padded", "nul"],
)
def test_rejected_text_stores_nothing(
    client: TestClient,
    sync_engine: Engine,
    storage_dir: Path,
    text: str,
    code: str,
    detail: str,
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)

    resp = _paste(client, headers, opp["id"], text)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, code)
    assert resp.json()["detail"] == detail
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


@pytest.mark.parametrize("escaped", ["\\ud800", "a\\udfffb", "\\u0000"])
def test_lone_surrogate_or_nul_in_json_is_rejected(
    client: TestClient, sync_engine: Engine, storage_dir: Path, escaped: str
) -> None:
    """Sent as raw JSON: a JSON string may escape a lone surrogate that UTF-8 can't hold."""
    headers, opp = _owner_and_opportunity(client, sync_engine)
    body = '{"text": "note ' + escaped + ' here"}'

    resp = client.post(
        _text_url(opp["id"]),
        headers={**headers, "Content-Type": "application/json"},
        content=body.encode(),
    )

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "file_content_mismatch")
    assert resp.json()["detail"] == "Rejected: the text contains unsupported characters"
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_text_at_the_limit_with_multi_byte_characters_is_accepted(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    prefix = f"{uuid4()} "
    text = prefix + "é😀" * ((1_000_000 - len(prefix)) // 2)
    text += "x" * (1_000_000 - len(text))
    assert len(text) == 1_000_000

    resp = _paste(client, headers, opp["id"], f"\n{text}\n")

    assert resp.status_code == 201, resp.text
    assert resp.json()["size_bytes"] == len(text.encode())


def test_same_text_pasted_again_is_the_next_version(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    note = f"Customer needs SAP sync {uuid4()}"
    first = _paste(client, headers, opp["id"], note).json()

    resp = _paste(client, headers, opp["id"], f"\t{note}  ")

    assert resp.status_code == 201, resp.text
    second = resp.json()
    assert second["id"] == first["id"]
    assert (second["version"], second["version_count"]) == (2, 2)
    assert _source_count(sync_engine, opp["id"]) == 1
    assert _ref_count(sync_engine, _sha(note.encode())) == 2
    assert [e["payload"]["version"] for e in _events(sync_engine, opp["id"])] == [1, 2]


def test_text_matching_an_uploaded_txt_is_its_next_version(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)
    note = f"Größe {uuid4()}"
    uploaded = _upload(client, headers, opp["id"], "notes.txt", note.encode()).json()

    resp = _paste(client, headers, opp["id"], note)

    assert resp.status_code == 201, resp.text
    pasted = resp.json()
    assert pasted["id"] == uploaded["id"]
    assert (pasted["version"], pasted["filename"], pasted["kind"]) == (2, "Pasted text", "note")
    assert _ref_count(sync_engine, _sha(note.encode())) == 2


@pytest.mark.parametrize(
    "body",
    [{}, {"text": 123}, {"text": None}, {"text": ["a"]}, {"text": "a", "title": "x"}],
)
def test_bad_text_body_is_a_validation_error(
    client: TestClient, sync_engine: Engine, storage_dir: Path, body: dict[str, Any]
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)

    resp = client.post(_text_url(opp["id"]), headers=headers, json=body)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


@pytest.mark.parametrize("raw", [b"{not json", b"", b"\xff\xfe", b'"just a string"'])
def test_malformed_text_body_is_a_validation_error(
    client: TestClient, sync_engine: Engine, storage_dir: Path, raw: bytes
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)

    resp = client.post(
        _text_url(opp["id"]),
        headers={**headers, "Content-Type": "application/json"},
        content=raw,
    )

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_text_body_cap_covers_the_worst_case_escapes() -> None:
    assert intake.TEXT_BODY_MAX_BYTES >= 1_000_000 * len("\\ud83d\\ude00") + len('{"text":""}')


def test_oversized_text_content_length_is_rejected_before_reading(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    headers, opp = _owner_and_opportunity(client, sync_engine)

    def body() -> Iterator[bytes]:
        yield b'{"text": "x"}'

    resp = client.post(
        _text_url(opp["id"]),
        headers={
            **headers,
            "Content-Type": "application/json",
            "Content-Length": str(intake.TEXT_BODY_MAX_BYTES + 1),
        },
        content=body(),
    )

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "file_too_large")
    assert resp.json()["detail"] == "Rejected: longer than 1,000,000 characters"
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_oversized_streamed_text_body_stops_at_the_cap(
    client: TestClient, sync_engine: Engine, storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chunked, so there is no Content-Length; reading stops once the cap is passed."""
    monkeypatch.setattr(intake, "TEXT_BODY_MAX_BYTES", 1024)
    headers, opp = _owner_and_opportunity(client, sync_engine)

    def chunked() -> Iterator[bytes]:
        yield b'{"text": "'
        for _ in range(100):
            yield b"x" * 512
        yield b'"}'

    resp = client.post(
        _text_url(opp["id"]),
        headers={**headers, "Content-Type": "application/json"},
        content=chunked(),
    )

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "file_too_large")
    assert resp.json()["detail"] == "Rejected: longer than 1,000,000 characters"
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])


def test_paste_without_a_token_is_401_and_stores_nothing(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    _, opp = _owner_and_opportunity(client, sync_engine)

    resp = client.post(_text_url(opp["id"]), json={"text": f"note {uuid4()}"})

    assert resp.status_code == 401, resp.text
    assert_problem(resp.json(), 401, "token_missing")
    _assert_nothing_stored(sync_engine, storage_dir, opp["id"])
