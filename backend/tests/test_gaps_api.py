"""The Gaps API (Story 4.3): `GET …/gaps` and `POST …/gap-detections`, against a real,
migrated Postgres as psa_app, with the fake ModelGateway and hidden jobs of
`test_intake_extraction.py`."""

from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_gaps_detection import (
    detect_jobs,
    detections,
    extracted,
    gap,
    gaps_out,
)
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, EXTRACT, FakeGateway, drain, out, owner
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile


def _get(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/gaps", headers=headers)


def _start(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/gap-detections", headers=headers)


def test_before_any_detection_the_list_is_empty(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = owner(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    mine = _get(client, headers, opp["id"])
    theirs = _get(client, reader, opp["id"])

    assert mine.status_code == 200, mine.text
    assert mine.json() == {
        "items": [],
        "detection": None,
        "can_start_detection": True,
        "can_edit_questions": True,
    }
    assert theirs.json() == {
        "items": [],
        "detection": None,
        "can_start_detection": False,
        "can_edit_questions": False,
    }


def test_the_list_ranks_open_gaps_with_requirements_and_questions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway)
    queued = _get(client, headers, opp["id"]).json()
    assert queued["detection"] == {"status": "queued", "error_code": None}
    reqs = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    gateway.replies = [
        gaps_out(
            gap("Price indexation", ["R5"], category="commercial", impact="low"),
            gap("SAP interface type", ["R1"], impact="high", topic="SAP"),
            gap("Peak growth", ["R3", "R2"], category="data_volumes", impact="medium"),
            gap("SSO provider", ["R4"], category="security_and_compliance", impact="high"),
        )
    ]
    assert drain(db_url, DETECT) == ["succeeded"]

    body = _get(client, headers, opp["id"]).json()

    assert body["detection"] == {"status": "succeeded", "error_code": None}
    assert [(g["title"], g["impact"]) for g in body["items"]] == [
        ("SAP interface type", "high"),
        ("SSO provider", "high"),
        ("Peak growth", "medium"),
        ("Price indexation", "low"),
    ]
    sap, _, peak, _ = body["items"]
    assert sap["category"] == "integration_details"
    assert sap["trigger"] == {"kind": "agent_category", "category": "integration_details"}
    assert (sap["origin"], sap["status"], sap["row_version"]) == ("detected", "open", 1)
    assert sap["why_it_matters"] and sap["impact_basis"]
    assert sap["requirements"] == [
        {"id": reqs[0]["id"], "version": 1, "label": "R1", "excerpt": "Connect to SAP."}
    ]
    assert [r["label"] for r in peak["requirements"]] == ["R2", "R3"]
    question = sap["question"]
    assert (question["topic"], question["status"]) == ("SAP", "drafted")
    assert question["text"] == "Could you tell us about sap interface type?"
    assert question["status_changed_at"] and question["row_version"] == 1


def test_a_rerun_hides_the_earlier_gaps(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [gaps_out(gap("SAP interface type", ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]

    assert _start(client, headers, opp["id"]).status_code == 201
    gateway.replies = [gaps_out(gap("Uptime window", ["R2"], category="non_functional"))]
    assert drain(db_url, DETECT) == ["succeeded"]

    assert [g["title"] for g in _get(client, headers, opp["id"]).json()["items"]] == [
        "Uptime window"
    ]


def test_start_is_409_while_a_detection_is_queued_or_running(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway)

    queued = _start(client, headers, opp["id"])
    assert queued.status_code == 409, queued.text
    assert_problem(queued.json(), 409, "gap_detection_in_progress")

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE gaps_detections SET status = 'running' WHERE opportunity_id = :o"),
            {"o": opp["id"]},
        )
    assert _start(client, headers, opp["id"]).status_code == 409
    assert len(detect_jobs(sync_engine, opp["id"])) == 1


def test_a_failed_detection_is_shown_and_retried_by_a_collaborator_but_not_a_sales_rep(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    added = _add(client, headers, opp, rep_id)
    assert added.status_code == 200, added.text
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    assert _add(client, headers, added.json(), colleague_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    gateway.replies = [ModelUnavailableError("down")]
    assert drain(db_url, DETECT) == ["failed_retrying", "dead"]

    seen = _get(client, rep, opp["id"])
    assert seen.status_code == 200
    assert seen.json()["detection"] == {"status": "failed", "error_code": "model_unavailable"}
    assert seen.json()["can_start_detection"] is False
    assert _get(client, colleague, opp["id"]).json()["can_start_detection"] is True

    for forbidden in (rep, reader):
        response = _start(client, forbidden, opp["id"])
        assert response.status_code == 403, response.text
        assert_problem(response.json(), 403, "forbidden")
    hidden = _start(client, outsider, opp["id"])
    assert hidden.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert _get(client, outsider, opp["id"]).status_code == 404
    assert len(detections(sync_engine, opp["id"])) == 1

    started = _start(client, colleague, opp["id"])

    assert started.status_code == 201, started.text
    assert started.json() == {"status": "queued", "error_code": None}
    assert [d["status"] for d in detections(sync_engine, opp["id"])] == ["failed", "queued"]
    gateway.replies = [gaps_out(gap("SAP interface type", ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    assert [g["title"] for g in _get(client, rep, opp["id"]).json()["items"]] == [
        "SAP interface type"
    ]


def test_a_lost_detection_reads_as_failed_and_can_be_started_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway)
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE gaps_detections SET status = 'running', "
                "created_at = now() - interval '2 hours' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )

    assert _get(client, headers, opp["id"]).json()["detection"] == {
        "status": "failed",
        "error_code": "model_timeout",
    }
    assert _start(client, headers, opp["id"]).status_code == 201
    lost, new = detections(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert new["status"] == "queued"


def test_ids_must_be_uuids_and_a_token_is_needed(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = owner(client, sync_engine)
    assert _get(client, headers, "nope").status_code == 422
    assert _start(client, headers, "nope").status_code == 422
    opp_id = str(uuid4())
    assert client.get(f"{BASE}/{opp_id}/gaps").status_code == 401
    assert client.post(f"{BASE}/{opp_id}/gap-detections").status_code == 401


def test_a_superseded_requirement_reads_as_superseded_with_its_original_excerpt(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [gaps_out(gap("SAP interface type", ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    (before,) = _get(client, headers, opp["id"]).json()["items"]
    extraction_tests._requeue(db_url, opp["id"])  # a re-extraction supersedes R1
    gateway.replies = [out(("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]))]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    (after,) = _get(client, headers, opp["id"]).json()["items"]  # its detection hasn't run
    assert after["requirements"] == [
        {
            "id": before["requirements"][0]["id"],
            "version": 1,
            "label": "Superseded",
            "excerpt": "Connect to SAP.",
        }
    ]


def test_the_excerpt_stays_the_text_of_the_version_the_gap_cites(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [gaps_out(gap("SAP interface type", ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    reqs = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    edited = client.patch(
        f"{BASE}/{opp['id']}/requirements/{reqs[0]['id']}",
        headers={**headers, "If-Match": f'"{reqs[0]["row_version"]}"'},
        json={"text": "Connect to SAP EWM over IDocs."},
    )
    assert edited.status_code == 200, edited.text

    (item,) = _get(client, headers, opp["id"]).json()["items"]

    assert item["requirements"] == [
        {"id": reqs[0]["id"], "version": 1, "label": "R1", "excerpt": "Connect to SAP."}
    ]
