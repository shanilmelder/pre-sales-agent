"""The passage API (Story 2.5 Part B): `GET …/passages/{passage_id}`, against a real, migrated
Postgres as psa_app, with the fake ModelGateway of `test_intake_extraction.py`."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.storage import BlobStore
from tests import test_intake_extraction as extraction_tests
from tests.test_health import assert_problem
from tests.test_intake_extraction import (
    BASE,
    EXTRACT,
    PARSE,
    FakeGateway,
    drain,
    out,
    parsed,
    upload,
)
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client


def _get(client: TestClient, headers: dict[str, str], opp_id: str, passage_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/passages/{passage_id}", headers=headers)


def _evidence(client: TestClient, headers: dict[str, str], opp_id: str) -> list[dict[str, Any]]:
    items = client.get(f"{BASE}/{opp_id}/requirements", headers=headers).json()["items"]
    return [e for item in items for e in item["evidence"]]


def _filler(n: int) -> str:
    return " ".join(f"word{i:03d}" for i in range(n))


def test_a_passage_comes_with_its_span_exactly_and_trimmed_context(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    quote = "The system must connect to SAP"
    text = f"{_filler(15)} {quote} {_filler(100)} {uuid4()}"  # quote at offset 120
    assert text.index(quote) == 120
    headers, opp, (s1,) = parsed(client, sync_engine, db_url, ("call.txt", text))
    gateway.replies = [out(("Connect to SAP.", "integration", [("S1", quote)]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (evidence,) = _evidence(client, headers, opp["id"])

    resp = _get(client, headers, opp["id"], evidence["passage_id"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == quote
    assert body["before"] == text[:120]  # within 300 of the start: whole, no ellipsis
    assert body["after"].endswith("…")
    assert len(body["after"]) <= 300
    assert text[120 + len(quote) :].startswith(body["after"].removesuffix("…"))
    assert {k: body[k] for k in ("passage_id", "source_id", "source_version", "filename")} == {
        "passage_id": evidence["passage_id"],
        "source_id": s1["id"],
        "source_version": 1,
        "filename": "call.txt",
    }
    assert body["label"] == "S1 · call.txt"


def test_a_passage_at_the_end_has_no_after_and_non_bmp_text_is_sliced_by_code_points(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    quote = "Users sign in with SSO."
    text = f"{uuid4()} \U0001f600\U0001f680 Note: {quote}"
    headers, opp, _ = parsed(client, sync_engine, db_url, ("mail.txt", text))
    gateway.replies = [out(("SSO.", "security", [("S1", quote)]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (evidence,) = _evidence(client, headers, opp["id"])

    body = _get(client, headers, opp["id"], evidence["passage_id"]).json()

    assert body["text"] == quote
    assert body["after"] == ""
    assert body["before"].endswith("\U0001f600\U0001f680 Note: ")
    assert "…" not in body["before"]


def test_readers_see_it_and_everyone_else_gets_the_opportunitys_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    quote = "Runs 24/7"
    headers, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"{quote}. {uuid4()}"))
    other_headers, other, _ = parsed(
        client, sync_engine, db_url, ("o.txt", f"Needs SSO. {uuid4()}")
    )
    gateway.replies = [
        out(("Always on.", "non_functional", [("S1", quote)])),
        out(("SSO.", "security", [("S1", "Needs SSO")])),
    ]
    assert drain(db_url, EXTRACT) == ["succeeded", "succeeded"]
    (mine,) = _evidence(client, headers, opp["id"])
    (theirs,) = _evidence(client, other_headers, other["id"])
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    head, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    assert _get(client, rep, opp["id"], mine["passage_id"]).status_code == 200
    assert _get(client, head, opp["id"], mine["passage_id"]).json()["text"] == quote

    not_found = [
        _get(client, outsider, opp["id"], mine["passage_id"]),  # non-reader
        _get(client, headers, opp["id"], theirs["passage_id"]),  # another Opportunity's
        _get(client, headers, opp["id"], str(uuid4())),  # unknown id
        _get(client, headers, str(uuid4()), mine["passage_id"]),  # unknown Opportunity
    ]
    for resp in not_found:
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
        assert resp.json()["detail"] == "No Opportunity with this id."


def test_a_passage_whose_text_cant_be_read_is_the_opportunitys_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway, storage_dir: Path
) -> None:
    quote = "Needs SSO"
    headers, opp, (s1,) = parsed(client, sync_engine, db_url, ("n.txt", f"{quote}. {uuid4()}"))
    gateway.replies = [out(("SSO.", "security", [("S1", quote)]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (evidence,) = _evidence(client, headers, opp["id"])
    with sync_engine.begin() as conn:
        sha = conn.execute(
            sa.text(
                "SELECT text_sha256 FROM intake_source_parses WHERE source_id = :s AND version = 1"
            ),
            {"s": s1["id"]},
        ).scalar_one()
    BlobStore(storage_dir).path_for(sha).unlink()

    resp = _get(client, headers, opp["id"], evidence["passage_id"])

    assert resp.status_code == 404, resp.text
    assert_problem(resp.json(), 404, "not_found")
    assert resp.json()["detail"] == "No Opportunity with this id."


def test_a_passage_of_an_older_version_keeps_that_versions_file_name_and_span(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    # A new version of a Source holds the same bytes (Story 2.1), so only the name differs.
    quote = "We must connect to SAP"
    text = f"Intro. {quote} today. {uuid4()}"
    headers, opp, (s1,) = parsed(client, sync_engine, db_url, ("call.txt", text))
    gateway.replies = [out(("Connect to SAP.", "integration", [("S1", quote)]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (evidence,) = _evidence(client, headers, opp["id"])
    v2 = upload(client, headers, opp["id"], "renamed-call.txt", text)
    assert (v2["id"], v2["version"]) == (s1["id"], 2)
    assert drain(db_url, PARSE) == ["succeeded"]

    body = _get(client, headers, opp["id"], evidence["passage_id"]).json()

    assert (body["source_id"], body["source_version"], body["filename"]) == (
        s1["id"],
        1,
        "call.txt",
    )
    assert body["label"] == "S1 · call.txt"
    assert (body["before"], body["text"]) == ("Intro. ", quote)
    assert body["after"] == text[text.index(quote) + len(quote) :]


def test_the_label_numbers_the_cited_source(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    quote = "SAP connectivity is a must"
    headers, opp, _ = parsed(
        client,
        sync_engine,
        db_url,
        ("call.txt", f"Runs 24/7. {uuid4()}"),
        ("mail.txt", f"{quote}. {uuid4()}"),
    )
    gateway.replies = [out(("Connect to SAP.", "integration", [("S2", quote)]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (evidence,) = _evidence(client, headers, opp["id"])

    body = _get(client, headers, opp["id"], evidence["passage_id"]).json()

    assert body["label"] == evidence["label"] == "S2 · mail.txt"
    assert body["text"] == quote


def test_ids_must_be_uuids_and_a_token_is_needed(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Someone", PSE)
    opp_id, passage_id = str(uuid4()), str(uuid4())
    assert _get(client, headers, "nope", passage_id).status_code == 422
    assert _get(client, headers, opp_id, "nope").status_code == 422
    assert client.get(f"{BASE}/{opp_id}/passages/{passage_id}").status_code == 401
