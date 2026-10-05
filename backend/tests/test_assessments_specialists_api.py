"""The specialist Assessments API (Epic 5 slice 5A): `GET …/assessments`,
`POST …/assessment-runs` and `POST …/assessment-runs/{run_id}/tasks/{agent}/retry`, against
a real, migrated Postgres as psa_app, with the per-agent fake gateway and hidden jobs."""

from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_specialists import (
    AGENTS,
    SECURITY,
    AgentGateway,
    assessment_out,
    effort,
    finding,
    install,
    prepared,
    replies,
    retry,
    run_rows,
    start,
    started,
)
from tests.test_health import assert_problem
from tests.test_intake_extraction import ASSESS, BASE, FakeGateway, drain, owner
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile


def _get(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/assessments", headers=headers)


def _slots(body: dict[str, Any]) -> dict[str, Any]:
    return {slot["agent"]: slot["assessment"] for slot in body["assessments"]}


def test_before_any_run_there_is_none(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = owner(client, sync_engine)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    mine = _get(client, headers, opp["id"])

    assert mine.status_code == 200, mine.text
    empty = [{"agent": agent, "assessment": None} for agent in AGENTS]
    assert mine.json() == {"run": None, "assessments": empty, "can_start": True}
    assert _get(client, reader, opp["id"]).json() == {
        "run": None,
        "assessments": empty,
        "can_start": False,
    }


def test_the_assessments_show_ranked_findings_chips_effort_and_totals(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    queued = _get(client, headers, opp["id"]).json()
    assert queued["run"]["id"] == body["id"]
    assert queued["run"]["status"] == "queued"
    assert drain(db_url, ASSESS) == ["succeeded"]

    view = _get(client, headers, opp["id"]).json()

    assert view["can_start"] is True
    run = view["run"]
    assert (run["id"], run["status"]) == (body["id"], "succeeded")
    assert [(t["agent"], t["status"], t["error_code"]) for t in run["tasks"]] == [
        (agent, "succeeded", None) for agent in AGENTS
    ]
    assert [slot["agent"] for slot in view["assessments"]] == list(AGENTS)
    engineering = _slots(view)["engineering_agent"]
    assert (engineering["version"], engineering["status"], engineering["run_id"]) == (
        1,
        "current",
        body["id"],
    )
    assert (engineering["recommendation"], engineering["confidence"]) == (
        "proceed_with_conditions",
        "medium",
    )
    assert engineering["confidence_basis"] == "Volumes are known; the interface details are not."
    assert engineering["counts"] == {"critical": 1, "high": 1, "medium": 1, "low": 0}
    assert [(f["severity"], f["position"], f["kind"]) for f in engineering["findings"]] == [
        ("critical", 1, "risk"),
        ("high", 2, "constraint"),
        ("medium", 3, "risk"),
    ]
    uptime = engineering["findings"][2]
    assert uptime["title"] == "Uptime target needs redundant controls"
    assert uptime["detail"] == "Nothing shows uptime target needs redundant controls is settled."
    assert uptime["requirements"] == [  # in Requirement order, not as cited
        {"id": reqs[0]["id"], "version": 1, "label": "R1", "excerpt": "Connect to SAP."},
        {"id": reqs[1]["id"], "version": 1, "label": "R2", "excerpt": "Runs 24/7."},
    ]
    assert [(e["requirement"]["label"], e["hours"], e["basis"]) for e in engineering["effort"]] == [
        ("R1", 40.0, "Sized R1."),
        ("R3", 24.3, "Sized R3."),
    ]
    assert engineering["total_hours"] == 64.3
    pm = _slots(view)["pm_agent"]
    assert [e["requirement"]["label"] for e in pm["effort"]] == ["R1", "R2", "R5"]
    assert pm["total_hours"] == 26.5
    security = _slots(view)["security_agent"]
    assert (security["effort"], security["total_hours"]) == ([], 0.0)


def test_a_rerun_shows_v2_and_hides_v1(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    fake = install(AgentGateway(replies()))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    fake.replies["engineering_agent"] = [assessment_out(finding("Second look", ["R2"]))]
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]

    engineering = _slots(_get(client, headers, opp["id"]).json())["engineering_agent"]

    assert (engineering["version"], engineering["status"]) == (2, "current")
    assert [f["title"] for f in engineering["findings"]] == ["Second look"]


def test_start_is_409_while_a_run_is_queued_or_running(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    started(client, headers, opp["id"])

    queued = start(client, headers, opp["id"])
    assert queued.status_code == 409, queued.text
    assert_problem(queued.json(), 409, "assessment_in_progress")

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE assessments_runs SET status = 'running' WHERE opportunity_id = :o"),
            {"o": opp["id"]},
        )
    running = start(client, headers, opp["id"])
    assert running.status_code == 409
    assert_problem(running.json(), 409, "assessment_in_progress")
    assert len(run_rows(sync_engine, opp["id"])) == 1


def test_who_may_start_and_retry_and_who_may_read(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    opp = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    added = _add(client, headers, opp, rep_id)
    assert added.status_code == 200, added.text
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    assert _add(client, headers, added.json(), colleague_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    for forbidden in (rep, reader):
        response = start(client, forbidden, opp["id"])
        assert response.status_code == 403, response.text
        assert_problem(response.json(), 403, "forbidden")
    hidden = start(client, outsider, opp["id"])
    assert hidden.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert run_rows(sync_engine, opp["id"]) == []

    install(AgentGateway(replies(security_agent=[ModelUnavailableError("down")])))
    body = started(client, colleague, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    seen = _get(client, rep, opp["id"])
    assert seen.status_code == 200
    assert seen.json()["can_start"] is False
    assert seen.json()["run"]["status"] == "partially_failed"
    tasks = {t["agent"]: t for t in seen.json()["run"]["tasks"]}
    assert (tasks["security_agent"]["status"], tasks["security_agent"]["error_code"]) == (
        "failed",
        "model_unavailable",
    )
    assert _slots(seen.json())["security_agent"] is None
    assert _get(client, reader, opp["id"]).status_code == 200
    assert _get(client, outsider, opp["id"]).status_code == 404
    for forbidden in (rep, reader):
        assert retry(client, forbidden, opp["id"], body["id"], "security_agent").status_code == 403
    assert retry(client, outsider, opp["id"], body["id"], "security_agent").status_code == 404

    retried = retry(client, colleague, opp["id"], body["id"], "security_agent")
    assert retried.status_code == 201, retried.text


def test_retry_is_only_for_a_failed_task_of_the_latest_finished_run(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    fake = install(AgentGateway(replies(security_agent=[ModelUnavailableError("down")])))
    first = started(client, headers, opp["id"])

    busy = retry(client, headers, opp["id"], first["id"], "security_agent")
    assert busy.status_code == 409
    assert_problem(busy.json(), 409, "assessment_in_progress")

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    succeeded = retry(client, headers, opp["id"], first["id"], "pm_agent")
    assert succeeded.status_code == 409
    assert_problem(succeeded.json(), 409, "assessment_task_not_failed")
    unknown = retry(client, headers, opp["id"], str(uuid4()), "security_agent")
    assert unknown.status_code == 404
    assert_problem(unknown.json(), 404, "not_found")
    assert retry(client, headers, opp["id"], first["id"], "sales_agent").status_code == 422
    assert retry(client, headers, opp["id"], "nope", "security_agent").status_code == 422

    fake.replies["security_agent"] = [SECURITY]
    second = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    older = retry(client, headers, opp["id"], first["id"], "security_agent")
    assert older.status_code == 409
    assert_problem(older.json(), 409, "assessment_task_not_failed")

    other_headers, other = owner(client, sync_engine)  # another Opportunity's run is unknown
    assert retry(client, other_headers, other["id"], second["id"], "pm_agent").status_code == 404


def test_a_lost_run_reads_as_failed_and_can_be_started_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    install(
        AgentGateway(
            replies(
                engineering_agent=[
                    assessment_out(finding("SAP fields", ["R1"]), efforts=(effort("R1", 3),))
                ]
            )
        )
    )
    started(client, headers, opp["id"])
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE assessments_runs SET status = 'running', "
                "queued_at = now() - interval '2 hours' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE assessments_tasks SET status = 'succeeded' WHERE agent = 'pm_agent' "
                "AND run_id IN (SELECT id FROM assessments_runs WHERE opportunity_id = :o)"
            ),
            {"o": opp["id"]},
        )

    run = _get(client, headers, opp["id"]).json()["run"]
    assert run["status"] == "partially_failed"
    assert [(t["agent"], t["status"], t["error_code"]) for t in run["tasks"]] == [
        ("engineering_agent", "failed", "model_timeout"),
        ("pm_agent", "succeeded", None),
        ("security_agent", "failed", "model_timeout"),
    ]
    assert start(client, headers, opp["id"]).status_code == 201
    lost, new = run_rows(sync_engine, opp["id"])
    assert (lost["status"], new["status"]) == ("partially_failed", "queued")


def test_ids_must_be_uuids_and_a_token_is_needed(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = owner(client, sync_engine)
    assert _get(client, headers, "nope").status_code == 422
    assert start(client, headers, "nope").status_code == 422
    opp_id = str(uuid4())
    assert client.get(f"{BASE}/{opp_id}/assessments").status_code == 401
    assert client.post(f"{BASE}/{opp_id}/assessment-runs").status_code == 401
    assert (
        client.post(f"{BASE}/{opp_id}/assessment-runs/{uuid4()}/tasks/pm_agent/retry").status_code
        == 401
    )


def test_a_superseded_requirement_reads_as_superseded(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    install(
        AgentGateway(
            replies(
                engineering_agent=[
                    assessment_out(
                        finding("SAP custom fields", ["R1"]),
                        efforts=(effort("R1", 8), effort("R2", 4)),
                    )
                ]
            )
        )
    )
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    extraction_tests._requeue(db_url, opp["id"])  # a re-extraction supersedes R1
    provider.install(gateway)
    gateway.replies = [
        extraction_tests.out(("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]))
    ]
    assert drain(db_url, extraction_tests.EXTRACT) == ["succeeded"]

    engineering = _slots(_get(client, headers, opp["id"]).json())["engineering_agent"]

    (requirement,) = engineering["findings"][0]["requirements"]
    assert (requirement["label"], requirement["excerpt"]) == ("Superseded", "Connect to SAP.")
    # The re-extraction supersedes both Requirements the rows sized (its "Runs 24/7." is new).
    assert sorted(
        (e["requirement"]["label"], e["requirement"]["excerpt"]) for e in engineering["effort"]
    ) == [("Superseded", "Connect to SAP."), ("Superseded", "Runs 24/7.")]
    assert engineering["total_hours"] == 12.0
