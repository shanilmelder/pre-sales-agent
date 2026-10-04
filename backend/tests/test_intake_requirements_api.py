"""The Requirements API (Story 2.5 Part A): `GET …/requirements` and `POST …/extractions`,
against a real, migrated Postgres as psa_app, with the fake ModelGateway of
`test_intake_extraction.py` (whose fixtures keep this module's jobs out of other claimers'
reach)."""

from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_intake_extraction as extraction_tests
from tests.test_health import assert_problem
from tests.test_intake_extraction import (
    BASE,
    EXTRACT,
    FakeGateway,
    drain,
    extractions,
    jobs,
    out,
    owner,
    parsed,
)
from tests.test_opportunities import PSE, _add, _user

# The extraction tests' fixtures: a temp store, hidden jobs, the fake gateway, the client.
storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client


def _get(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/requirements", headers=headers)


def _start(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/extractions", headers=headers)


def test_before_any_extraction_the_list_is_empty(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = owner(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    mine = _get(client, headers, opp["id"])
    theirs = _get(client, reader, opp["id"])

    assert mine.status_code == 200, mine.text
    assert mine.json() == {
        "items": [],
        "extraction": None,
        "can_start_extraction": True,
        "can_edit_requirements": True,
    }
    assert theirs.json() == {
        "items": [],
        "extraction": None,
        "can_start_extraction": False,
        "can_edit_requirements": False,
    }


def test_the_list_shows_requirements_with_evidence_labels(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (s1, s2) = parsed(
        client,
        sync_engine,
        db_url,
        ("call.txt", f"We must connect to SAP. Runs 24/7. {uuid4()}"),
        ("mail.txt", f"SAP connectivity is a must. {uuid4()}"),
    )
    queued = _get(client, headers, opp["id"]).json()
    assert queued["items"] == []
    assert queued["extraction"] == {"status": "queued", "error_code": None, "source_count": None}
    gateway.replies = [
        out(
            (
                "Connect to SAP.",
                "integration",
                [("S2", "SAP connectivity is a must"), ("S1", "We must connect to SAP")],
            ),
            ("Runs 24/7.", "non_functional", [("S1", "Runs 24/7")]),
        )
    ]
    assert drain(db_url, EXTRACT) == ["succeeded"]

    body = _get(client, headers, opp["id"]).json()

    assert body["extraction"] == {"status": "succeeded", "error_code": None, "source_count": 2}
    sap, uptime = body["items"]
    assert (sap["text"], sap["classification"], sap["origin"]) == (
        "Connect to SAP.",
        "integration",
        "extracted",
    )
    assert (sap["locked_by_human"], sap["version"], sap["row_version"]) == (False, 1, 1)
    assert [
        (e["label"], e["source_id"], e["source_version"], e["filename"]) for e in sap["evidence"]
    ] == [
        ("S1 · call.txt", s1["id"], 1, "call.txt"),
        ("S2 · mail.txt", s2["id"], 1, "mail.txt"),
    ]
    assert all(e["passage_id"] for e in sap["evidence"])
    assert [e["label"] for e in uptime["evidence"]] == ["S1 · call.txt"]
    assert uptime["classification"] == "non_functional"


def test_start_is_409_while_an_extraction_is_queued_or_running(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs SSO {uuid4()}"))

    queued = _start(client, headers, opp["id"])
    assert queued.status_code == 409, queued.text
    assert_problem(queued.json(), 409, "extraction_in_progress")

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE intake_extractions SET status = 'running' WHERE opportunity_id = :o"),
            {"o": opp["id"]},
        )
    running = _start(client, headers, opp["id"])
    assert running.status_code == 409
    assert len(jobs(sync_engine, opp["id"])) == 1


def test_a_failed_extraction_is_shown_and_retried_by_a_collaborator(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs SSO {uuid4()}"))
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    gateway.replies = [ModelUnavailableError("down")]
    assert drain(db_url, EXTRACT) == ["failed_retrying", "dead"]

    body = _get(client, rep, opp["id"]).json()
    assert body["extraction"] == {
        "status": "failed",
        "error_code": "model_unavailable",
        "source_count": 1,
    }
    assert body["can_start_extraction"] is True

    forbidden = _start(client, reader, opp["id"])
    assert forbidden.status_code == 403, forbidden.text
    assert_problem(forbidden.json(), 403, "forbidden")
    hidden = _start(client, outsider, opp["id"])
    assert hidden.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert _get(client, outsider, opp["id"]).status_code == 404
    assert len(extractions(sync_engine, opp["id"])) == 1

    started = _start(client, rep, opp["id"])

    assert started.status_code == 201, started.text
    assert started.json() == {"status": "queued", "error_code": None, "source_count": None}
    assert [e["status"] for e in extractions(sync_engine, opp["id"])] == ["failed", "queued"]
    assert [j["status"] for j in jobs(sync_engine, opp["id"])] == ["dead", "queued"]
    assert _get(client, rep, opp["id"]).json()["extraction"]["status"] == "queued"

    # The retry runs and succeeds.
    gateway.replies = [out(("SSO.", "security", [("S1", "Needs SSO")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    assert [r["text"] for r in _get(client, rep, opp["id"]).json()["items"]] == ["SSO."]


def test_ids_must_be_uuids_and_a_token_is_needed(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = owner(client, sync_engine)
    assert _get(client, headers, "nope").status_code == 422
    assert _start(client, headers, "nope").status_code == 422
    opp_id = str(uuid4())
    assert client.get(f"{BASE}/{opp_id}/requirements").status_code == 401
    assert client.post(f"{BASE}/{opp_id}/extractions").status_code == 401


def test_a_lost_extraction_reads_as_failed_and_can_be_started_again(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs SSO {uuid4()}"))
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE intake_extractions SET status = 'running', source_count = 1, "
                "created_at = now() - interval '2 hours' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )

    body = _get(client, headers, opp["id"]).json()
    assert body["extraction"] == {
        "status": "failed",
        "error_code": "model_timeout",
        "source_count": 1,
    }

    started = _start(client, headers, opp["id"])

    assert started.status_code == 201, started.text
    lost, new = extractions(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert lost["finished_at"] is not None
    assert new["status"] == "queued"


def test_a_recent_running_extraction_still_blocks_a_start(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs SSO {uuid4()}"))
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE intake_extractions SET status = 'running', "
                "created_at = now() - interval '20 minutes' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )
    assert _get(client, headers, opp["id"]).json()["extraction"]["status"] == "running"
    assert _start(client, headers, opp["id"]).status_code == 409
