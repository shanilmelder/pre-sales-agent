"""The Red Team API (Story 6.5): `GET …/red-team` and `POST …/red-team-reviews`, against a real,
migrated Postgres as psa_app, with the fake ModelGateway and hidden jobs of
`test_intake_extraction.py`."""

from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_assessments_red_team as red_team_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_red_team import FIVE, drafted, finding, findings_out, runs
from tests.test_estimates_draft import est_line, lines_out
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DRAFT, RED_TEAM, FakeGateway, drain, owner
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_review_profile = red_team_tests._review_profile


def _get(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/red-team", headers=headers)


def _start(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/red-team-reviews", headers=headers)


def test_before_any_review_there_is_none(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = owner(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    mine = _get(client, headers, opp["id"])

    assert mine.status_code == 200, mine.text
    assert mine.json() == {"review": None, "run": None, "can_start": True}
    assert _get(client, reader, opp["id"]).json() == {
        "review": None,
        "run": None,
        "can_start": False,
    }


def test_the_review_lists_findings_critical_first_with_chips_and_counts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    assert _get(client, headers, opp["id"]).json()["run"] == {
        "status": "queued",
        "error_code": None,
    }
    reqs = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()["version"]
    gateway.replies = [findings_out(*FIVE)]
    assert drain(db_url, RED_TEAM) == ["succeeded"]

    body = _get(client, headers, opp["id"]).json()

    assert body["run"] == {"status": "succeeded", "error_code": None}
    assert body["can_start"] is True
    review = body["review"]
    assert (review["version"], review["status"], review["dropped_count"]) == (1, "current", 0)
    assert (review["estimate_version_id"], review["estimate_version"]) == (estimate["id"], 1)
    assert review["counts"] == {"critical": 1, "high": 1, "medium": 2, "low": 1}
    assert [(f["severity"], f["position"]) for f in review["findings"]] == [
        ("critical", 3),
        ("high", 4),
        ("medium", 1),
        ("medium", 5),
        ("low", 2),
    ]
    peak = review["findings"][0]
    assert peak["category"] == "requirement_incomplete"
    assert peak["title"] == "Peak 900 orders/hour — no seasonal profile"
    assert peak["requirements"] == [
        {"id": reqs[2]["id"], "version": 1, "label": "R3", "excerpt": "Peak 900 orders/hour."}
    ]
    # Line chips in the grid's order: functional before commercial.
    assert [(line["title"], line["section"], line["effort_hours"]) for line in peak["lines"]] == [
        ("Order throughput", "functional", 24.5),
        ("Project management", "commercial", 10.0),
    ]
    eur = review["findings"][3]
    assert [r["label"] for r in eur["requirements"]] == ["R1", "R5"]
    assert eur["lines"] == []


def test_a_rereview_shows_v2_and_hides_v1(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [findings_out(*FIVE)]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    assert client.post(f"{BASE}/{opp['id']}/estimate-drafts", headers=headers).status_code == 201
    gateway.replies = [lines_out(est_line("Everything", ["R1", "R2", "R3", "R4", "R5"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    gateway.replies = [findings_out(finding("One line for everything", ["R1"]))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]

    review = _get(client, headers, opp["id"]).json()["review"]

    assert (review["version"], review["status"], review["estimate_version"]) == (2, "current", 2)
    assert [f["title"] for f in review["findings"]] == ["One line for everything"]


def test_start_is_409_while_a_review_is_queued_or_running(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway, count=2)

    queued = _start(client, headers, opp["id"])
    assert queued.status_code == 409, queued.text
    assert_problem(queued.json(), 409, "red_team_review_in_progress")

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE assessments_red_team_runs SET status = 'running' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )
    assert _start(client, headers, opp["id"]).status_code == 409
    assert len(runs(sync_engine, opp["id"])) == 1


def test_a_failed_review_is_shown_and_retried_by_a_collaborator_but_not_a_sales_rep(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    opp = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    added = _add(client, headers, opp, rep_id)
    assert added.status_code == 200, added.text
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    assert _add(client, headers, added.json(), colleague_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    gateway.replies = [ModelUnavailableError("down")]
    assert drain(db_url, RED_TEAM) == ["failed_retrying", "dead"]

    seen = _get(client, rep, opp["id"])
    assert seen.status_code == 200
    assert seen.json()["run"] == {"status": "failed", "error_code": "model_unavailable"}
    assert seen.json()["can_start"] is False
    assert _get(client, reader, opp["id"]).status_code == 200
    assert _get(client, colleague, opp["id"]).json()["can_start"] is True

    for forbidden in (rep, reader):
        response = _start(client, forbidden, opp["id"])
        assert response.status_code == 403, response.text
        assert_problem(response.json(), 403, "forbidden")
    hidden = _start(client, outsider, opp["id"])
    assert hidden.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert _get(client, outsider, opp["id"]).status_code == 404
    assert len(runs(sync_engine, opp["id"])) == 1

    started = _start(client, colleague, opp["id"])

    assert started.status_code == 201, started.text
    assert started.json() == {"status": "queued", "error_code": None}
    assert [r["status"] for r in runs(sync_engine, opp["id"])] == ["failed", "queued"]
    gateway.replies = [findings_out(finding("SAP custom fields", ["R1"]))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    review = _get(client, rep, opp["id"]).json()["review"]
    assert [f["title"] for f in review["findings"]] == ["SAP custom fields"]


def test_a_lost_review_reads_as_failed_and_can_be_started_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE assessments_red_team_runs SET status = 'running', "
                "created_at = now() - interval '2 hours' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )

    assert _get(client, headers, opp["id"]).json()["run"] == {
        "status": "failed",
        "error_code": "model_timeout",
    }
    assert _start(client, headers, opp["id"]).status_code == 201
    lost, new = runs(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert new["status"] == "queued"


def test_ids_must_be_uuids_and_a_token_is_needed(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = owner(client, sync_engine)
    assert _get(client, headers, "nope").status_code == 422
    assert _start(client, headers, "nope").status_code == 422
    opp_id = str(uuid4())
    assert client.get(f"{BASE}/{opp_id}/red-team").status_code == 401
    assert client.post(f"{BASE}/{opp_id}/red-team-reviews").status_code == 401


def test_a_superseded_requirement_reads_as_superseded(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [findings_out(finding("SAP custom fields", ["R1"]))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    extraction_tests._requeue(db_url, opp["id"])  # a re-extraction supersedes R1
    gateway.replies = [
        extraction_tests.out(("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]))
    ]
    assert drain(db_url, extraction_tests.EXTRACT) == ["succeeded"]

    (requirement,) = _get(client, headers, opp["id"]).json()["review"]["findings"][0][
        "requirements"
    ]
    assert (requirement["label"], requirement["excerpt"]) == ("Superseded", "Connect to SAP.")
