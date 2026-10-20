"""The Opportunity Source viewer (Story 2.3) against a real, migrated Postgres as psa_app:
`GET …/sources/{source_id}/versions/{version}/text` and `POST …/download-link`, and the
signed download it links to.

Parse jobs run through the real runner, limited to this test's Opportunities (see
`test_intake_parse_job`).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_intake_parse_job as parse_tests
from tests.test_health import assert_problem
from tests.test_intake_parse_job import BASE, _drain, _owner, _upload
from tests.test_intake_parsers import fixture
from tests.test_opportunities import _add, _create, _user

storage_dir = parse_tests.storage_dir
parse_timeout = parse_tests.parse_timeout
_own_opportunities = parse_tests._own_opportunities
client = parse_tests.client

REP = "sales_representative"


def _text(client: TestClient, headers: dict[str, str], opp_id: str, source_id: str, v: int) -> Any:
    return client.get(f"{BASE}/{opp_id}/sources/{source_id}/versions/{v}/text", headers=headers)


def _link(client: TestClient, headers: dict[str, str], opp_id: str, source_id: str, v: int) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/sources/{source_id}/versions/{v}/download-link", headers=headers
    )


def _rep_member(
    client: TestClient, engine: Engine, headers: dict[str, str], opp: dict[str, Any]
) -> dict[str, str]:
    rep, rep_id = _user(client, engine, "Rep Person", REP)
    assert _add(client, headers, opp, rep_id).status_code == 200
    return rep


def test_a_reader_gets_the_exact_stored_text_of_a_parsed_version(
    client: TestClient, sync_engine: Engine, db_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    headers, opp = _owner(client, sync_engine)
    rep = _rep_member(client, sync_engine, headers, opp)
    text = f"a\r\nb é secret customer words {opp['id']}"
    source = _upload(client, headers, opp["id"], "secret-name.txt", text.encode())
    assert _drain(db_url) == ["succeeded"]

    with caplog.at_level(logging.DEBUG):
        resp = _text(client, rep, opp["id"], source["id"], 1)

    assert resp.status_code == 200, resp.text
    want = f"a\nb é secret customer words {opp['id']}"
    assert resp.json() == {"version": 1, "char_count": len(want), "text": want}
    assert _text(client, headers, opp["id"], source["id"], 1).json()["text"] == want
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    assert "secret" not in logged


def test_the_text_is_404_until_parsed_and_outside_the_opportunity(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    other = _create(client, headers)  # the same owner can read it
    queued = _upload(client, headers, opp["id"], "a.txt", f"queued {opp['id']}".encode())
    stranger, _ = _user(client, sync_engine, "Someone Else", "presales_engineer")

    not_parsed = _text(client, headers, opp["id"], queued["id"], 1)
    assert not_parsed.status_code == 404
    assert_problem(not_parsed.json(), 404, "not_found")

    assert _drain(db_url) == ["succeeded"]
    assert _text(client, headers, opp["id"], queued["id"], 1).status_code == 200
    for resp in (
        _text(client, headers, opp["id"], queued["id"], 2),  # no such version
        _text(client, headers, opp["id"], str(uuid4()), 1),  # no such Source
        _text(client, headers, other["id"], queued["id"], 1),  # another Opportunity's path
        _text(client, stranger, opp["id"], queued["id"], 1),  # can't read the Opportunity
    ):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
    assert _text(client, headers, opp["id"], queued["id"], 0).status_code == 422


def test_a_failed_version_has_no_text(client: TestClient, sync_engine: Engine, db_url: str) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "broken.pdf", fixture("corrupt.pdf"))
    assert _drain(db_url) == ["succeeded"]

    resp = _text(client, headers, opp["id"], source["id"], 1)

    assert resp.status_code == 404
    assert_problem(resp.json(), 404, "not_found")


def test_a_sales_representative_downloads_the_original_file(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    rep = _rep_member(client, sync_engine, headers, opp)
    data = f"original bytes\r\n{opp['id']}".encode()
    source = _upload(client, headers, opp["id"], "call notes.txt", data)

    resp = _link(client, rep, opp["id"], source["id"], 1)  # works before parsing too

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"url", "expires_at"}
    assert body["url"].startswith("/api/v1/downloads/")
    expires = datetime.fromisoformat(body["expires_at"])
    assert datetime.now(UTC) < expires < datetime.now(UTC) + timedelta(hours=1)

    file = client.get(body["url"])
    assert file.status_code == 200
    assert file.content == data  # unchanged: no CRLF normalisation
    assert file.headers["content-type"] == "application/octet-stream"
    assert file.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in file.headers["content-disposition"]
    assert "call%20notes.txt" in file.headers["content-disposition"] or (
        "call notes.txt" in file.headers["content-disposition"]
    )

    tampered = client.get(body["url"][:-2] + ("AA" if not body["url"].endswith("AA") else "BB"))
    assert tampered.status_code == 403
    assert_problem(tampered.json(), 403, "forbidden")


def test_the_download_link_is_404_outside_the_opportunity(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, opp = _owner(client, sync_engine)
    other = _create(client, headers)  # the same owner can read it
    source = _upload(client, headers, opp["id"], "a.txt", f"x {opp['id']}".encode())
    stranger, _ = _user(client, sync_engine, "Someone Else", "presales_engineer")

    for resp in (
        _link(client, headers, opp["id"], source["id"], 2),
        _link(client, headers, other["id"], source["id"], 1),
        _link(client, stranger, opp["id"], source["id"], 1),
    ):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
