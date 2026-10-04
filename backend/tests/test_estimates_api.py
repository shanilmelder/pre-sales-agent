"""The Estimate API (Story 8.1): `GET …/estimate` and `POST …/estimate-drafts`, against a real,
migrated Postgres as psa_app, with the fake ModelGateway and hidden jobs of
`test_intake_extraction.py`."""

from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.main_api import create_app
from app.platform.config import Settings
from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_estimates_draft import SIX, detected, drafts, est_line, lines_out
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DRAFT, FakeGateway, drain, owner
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile


def _get(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/estimate", headers=headers)


def _start(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/estimate-drafts", headers=headers)


def test_before_any_draft_there_is_no_version(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = owner(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    mine = _get(client, headers, opp["id"])
    theirs = _get(client, reader, opp["id"])

    assert mine.status_code == 200, mine.text
    assert mine.json() == {"version": None, "draft": None, "can_start_draft": True}
    assert theirs.json() == {"version": None, "draft": None, "can_start_draft": False}


def test_the_estimate_has_sections_lines_and_server_totals(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    assert _get(client, headers, opp["id"]).json()["draft"] == {
        "status": "queued",
        "error_code": None,
    }
    reqs = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    gateway.replies = [
        lines_out(
            est_line(
                "SAP order interface",
                ["R1"],
                effort=10.0,
                mix={"engineer": 33, "project_manager": 33, "qa": 34},
            ),
            est_line("Single sign-on", ["R4"], section="security", effort=12.0),
            est_line("Order throughput", ["R3", "R2"], section="functional", effort=24.5),
            est_line(
                "Message mapping",
                ["R1"],
                effort=6.5,
                mix={"engineer": 100, "project_manager": 0, "qa": 0},
            ),
        )
    ]
    assert drain(db_url, DRAFT) == ["succeeded"]

    body = _get(client, headers, opp["id"]).json()

    assert body["draft"] == {"status": "succeeded", "error_code": None}
    assert body["can_start_draft"] is True
    version = body["version"]
    assert (version["version"], version["status"], version["template_version"]) == (
        1,
        "draft",
        "demo-1",
    )
    assert version["roles"] == ["engineer", "project_manager", "qa"]
    assert (version["uncovered_count"], version["dropped_count"]) == (1, 0)  # R5
    assert [s["section"] for s in version["sections"]] == ["functional", "integration", "security"]
    functional, integration, security = version["sections"]
    assert [line["title"] for line in integration["lines"]] == [
        "SAP order interface",
        "Message mapping",
    ]
    sap = integration["lines"][0]
    assert sap["role_mix"] == {"engineer": 33, "project_manager": 33, "qa": 34}
    assert sap["role_hours"] == {"engineer": 3.3, "project_manager": 3.3, "qa": 3.4}
    assert (sap["effort_hours"], sap["contingency_hours"], sap["total_hours"]) == (10.0, 0.0, 10.0)
    assert sap["basis"] == "Sized from sap order interface."
    assert sap["requirements"] == [
        {"id": reqs[0]["id"], "version": 1, "label": "R1", "excerpt": "Connect to SAP."}
    ]
    assert [r["label"] for r in functional["lines"][0]["requirements"]] == ["R2", "R3"]
    assert integration["subtotal"] == {
        "effort_hours": 16.5,
        "contingency_hours": 0.0,
        "total_hours": 16.5,
        "role_hours": {"engineer": 9.8, "project_manager": 3.3, "qa": 3.4},
    }
    assert security["subtotal"]["role_hours"] == {
        "engineer": 7.2,
        "project_manager": 2.4,
        "qa": 2.4,
    }
    assert version["totals"] == {
        "effort_hours": 53.0,
        "contingency_hours": 0.0,
        "total_hours": 53.0,
        "role_hours": {"engineer": 31.7, "project_manager": 10.6, "qa": 10.7},
    }


def test_a_redraft_shows_v2_and_hides_v1(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    gateway.replies = [lines_out(*SIX)]
    assert drain(db_url, DRAFT) == ["succeeded"]

    assert _start(client, headers, opp["id"]).status_code == 201
    gateway.replies = [lines_out(est_line("Everything", ["R1", "R2", "R3", "R4", "R5"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]

    version = _get(client, headers, opp["id"]).json()["version"]
    assert (version["version"], version["status"]) == (2, "draft")
    assert [line["title"] for s in version["sections"] for line in s["lines"]] == ["Everything"]


def test_start_is_409_while_a_draft_is_queued_or_running(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)

    queued = _start(client, headers, opp["id"])
    assert queued.status_code == 409, queued.text
    assert_problem(queued.json(), 409, "estimate_draft_in_progress")

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE estimates_drafts SET status = 'running' WHERE opportunity_id = :o"),
            {"o": opp["id"]},
        )
    assert _start(client, headers, opp["id"]).status_code == 409
    assert len(drafts(sync_engine, opp["id"])) == 1


def test_a_failed_draft_is_shown_and_retried_by_a_collaborator_but_not_a_sales_rep(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    added = _add(client, headers, opp, rep_id)
    assert added.status_code == 200, added.text
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    assert _add(client, headers, added.json(), colleague_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    gateway.replies = [ModelUnavailableError("down")]
    assert drain(db_url, DRAFT) == ["failed_retrying", "dead"]

    seen = _get(client, rep, opp["id"])
    assert seen.status_code == 200
    assert seen.json()["draft"] == {"status": "failed", "error_code": "model_unavailable"}
    assert seen.json()["can_start_draft"] is False
    assert _get(client, reader, opp["id"]).status_code == 200
    assert _get(client, colleague, opp["id"]).json()["can_start_draft"] is True

    for forbidden in (rep, reader):
        response = _start(client, forbidden, opp["id"])
        assert response.status_code == 403, response.text
        assert_problem(response.json(), 403, "forbidden")
    hidden = _start(client, outsider, opp["id"])
    assert hidden.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert _get(client, outsider, opp["id"]).status_code == 404
    assert len(drafts(sync_engine, opp["id"])) == 1

    started = _start(client, colleague, opp["id"])

    assert started.status_code == 201, started.text
    assert started.json() == {"status": "queued", "error_code": None}
    assert [d["status"] for d in drafts(sync_engine, opp["id"])] == ["failed", "queued"]
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    version = _get(client, rep, opp["id"]).json()["version"]
    assert version["uncovered_count"] == 4


def test_a_lost_draft_reads_as_failed_and_can_be_started_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE estimates_drafts SET status = 'running', "
                "created_at = now() - interval '2 hours' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )

    assert _get(client, headers, opp["id"]).json()["draft"] == {
        "status": "failed",
        "error_code": "model_timeout",
    }
    assert _start(client, headers, opp["id"]).status_code == 201
    lost, new = drafts(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert new["status"] == "queued"


def test_ids_must_be_uuids_and_a_token_is_needed(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = owner(client, sync_engine)
    assert _get(client, headers, "nope").status_code == 422
    assert _start(client, headers, "nope").status_code == 422
    opp_id = str(uuid4())
    assert client.get(f"{BASE}/{opp_id}/estimate").status_code == 401
    assert client.post(f"{BASE}/{opp_id}/estimate-drafts").status_code == 401


def test_a_superseded_requirement_reads_as_superseded(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    extraction_tests._requeue(db_url, opp["id"])  # a re-extraction supersedes R1
    gateway.replies = [
        extraction_tests.out(("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]))
    ]
    assert drain(db_url, extraction_tests.EXTRACT) == ["succeeded"]

    version = _get(client, headers, opp["id"]).json()["version"]  # not re-drafted yet

    (requirement,) = version["sections"][0]["lines"][0]["requirements"]
    assert (requirement["label"], requirement["excerpt"]) == ("Superseded", "Connect to SAP.")


def test_no_endpoint_accepts_a_total() -> None:
    schema = create_app(Settings()).openapi()
    for path, operations in schema["paths"].items():
        if "estimate" not in path:
            continue
        for method, operation in operations.items():
            assert method in {"get", "post"}
            assert "requestBody" not in operation, (method, path)
