"""The Estimate built from the specialist Assessments (Story 8.3) against a real, migrated
Postgres as psa_app, with fake model gateways: the `finish_run` hook, superseding and
carrying, the Conflict re-check and markers, failed and empty runs, a late model draft, and
the read model's source and waiting state.

Reuses the fixtures of `test_intake_extraction.py`, `test_gaps_detection.py`,
`test_estimates_draft.py` and `test_assessments_specialists.py`: Opportunities with R1
"Connect to SAP." (integration), R2 "Runs 24/7." (non_functional) and R3 "Peak 900
orders/hour." (functional); assessment runs started by hand (the automatic one is left out
unless a test requests `auto_run`).
"""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.assessments.application.public import AssessmentAgent
from app.modules.estimates.application import assumptions as estimates_assumptions
from app.modules.estimates.application import public as estimates_public
from app.platform.config import Settings
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_specialists import (
    AgentGateway,
    _accept,
    _inputs,
    _mid_run,
    assessment_out,
    cancel,
    effort,
    finding,
    install,
    replies,
    retry,
    run_rows,
    started,
)
from tests.test_estimates_assumptions import by_title, condition
from tests.test_estimates_draft import est_line, line_rows, lines_out, link_rows, versions
from tests.test_gaps_detection import extracted, gap, gaps_out, requirement_rows, rows
from tests.test_intake_extraction import (
    ASSESS,
    BASE,
    DETECT,
    DRAFT,
    PROPOSE,
    RED_TEAM,
    FakeGateway,
    drain,
)

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run
auto_run = specialist_tests.auto_run

CREATED = "estimates.estimate_version.created"


@pytest.fixture(autouse=True)
def _proposal_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        estimates_assumptions,
        "proposal_settings",
        lambda: Settings(model_profile_chat="demo-chat"),
    )


def agent_out(*efforts: dict[str, Any], recommendation: str = "proceed_with_conditions") -> Any:
    return assessment_out(
        finding("Interface details open", ["R1"]), efforts=efforts, recommendation=recommendation
    )


# Engineering 20 h / PM 10 h / Security 4 h on R1; Engineering 8 h on R3.
HAPPY = replies(
    engineering_agent=[
        agent_out(effort("R1", 20, "Two interfaces."), effort("R3", 8, "One screen."))
    ],
    pm_agent=[agent_out(effort("R1", 10, "Vendor meetings."))],
    security_agent=[agent_out(effort("R1", 4, "Credential review."))],
)


def prepared(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with R1-R3 and one open Gap about R1; no Estimate, no run."""
    headers, opp = extracted(client, engine, db_url, gateway, count=3)
    gateway.replies = [gaps_out(gap("WMS version unknown", ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    return headers, opp


def run(client: TestClient, headers: dict[str, str], opp_id: str, db_url: str) -> dict[str, Any]:
    body = started(client, headers, opp_id)
    assert drain(db_url, ASSESS)[-1] in {"succeeded", "dead"}
    return body


def estimate(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/{opp_id}/estimate", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def lines_by_title(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["title"]: line for s in view["version"]["sections"] for line in s["lines"]}


def created_events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :t "
        "ORDER BY occurred_at, id",
        o=opp_id,
        t=CREATED,
    )


def jobs(engine: Engine, opp_id: str, job_type: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
        t=job_type,
        o=opp_id,
    )


def open_conflicts(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM conflicts_conflicts WHERE opportunity_id = :o AND status = 'open' "
        "ORDER BY created_at, id",
        o=opp_id,
    )


def edit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    line: dict[str, Any],
    hours: float = 32,
) -> None:
    response = client.patch(
        f"{BASE}/{opp_id}/estimate-lines/{line['id']}",
        headers={**headers, "If-Match": f'"{line["row_version"]}"'},
        json={"effort_hours": hours, "reason": "Reuse the existing connector"},
    )
    assert response.status_code == 200, response.text


# --- trigger --------------------------------------------------------------------------------


@pytest.mark.usefixtures("auto_run")
def test_gap_detection_queues_the_run_and_no_model_draft(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = prepared(client, sync_engine, db_url, gateway)

    assert [r["status"] for r in run_rows(sync_engine, opp["id"])] == ["queued"]
    assert jobs(sync_engine, opp["id"], DRAFT) == []
    assert (
        rows(sync_engine, "SELECT * FROM estimates_drafts WHERE opportunity_id = :o", o=opp["id"])
        == []
    )


# --- happy path -----------------------------------------------------------------------------


def test_a_finished_run_builds_a_version_from_the_assessments(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    install(AgentGateway(HAPPY))

    body = run(client, headers, opp["id"], db_url)

    (version,) = versions(sync_engine, opp["id"])
    assert (version["version"], version["status"], version["template_version"]) == (
        1,
        "draft",
        "demo-1",
    )
    assert (version["source"], str(version["source_run_id"])) == ("assessments", body["id"])
    assert (version["uncovered_count"], version["dropped_count"]) == (1, 0)  # R2 not sized
    first, second = line_rows(sync_engine, version["id"])
    assert (first["section"], first["title"], str(first["effort_hours"])) == (
        "functional",
        "Peak 900 orders/hour.",
        "8.0",
    )
    assert first["role_mix"] == {"engineer": 100, "project_manager": 0, "qa": 0}
    assert first["basis"] == "Engineering: One screen."
    assert (second["section"], second["title"], str(second["effort_hours"])) == (
        "integration",
        "Connect to SAP.",
        "34.0",
    )
    assert second["role_mix"] == {"engineer": 71, "project_manager": 29, "qa": 0}
    assert second["basis"] == (
        "Engineering: Two interfaces. · PM: Vendor meetings. · Security: Credential review."
    )
    (link,) = link_rows(sync_engine, second["id"])
    assert (link["requirement_id"], link["requirement_version"]) == (reqs[0]["id"], 1)

    # The trace: the system created it, with ids and counts only.
    (event,) = created_events(sync_engine, opp["id"])
    assert (event["actor_type"], event["actor_id"]) == (
        "system",
        "estimates.build_from_assessments",
    )
    assert (event["subject_type"], event["subject_id"]) == (
        "estimates.estimate_version",
        version["id"],
    )
    assert event["payload"] == {
        "version": 1,
        "template_version": "demo-1",
        "line_count": 2,
        "dropped_count": 0,
        "uncovered_count": 1,
        "requirement_count": 3,
        "superseded_count": 0,
        "carried_assumption_count": 0,
        "carried_edit_count": 0,
        "uncarried_edit_count": 0,
        "source": "assessments",
        "source_run_id": body["id"],
    }
    assert "SAP" not in str(event["payload"])
    # What follows every new version: its Assumption proposals and the Red Team Review.
    assert len(jobs(sync_engine, opp["id"], PROPOSE)) == 1
    assert len(jobs(sync_engine, opp["id"], RED_TEAM)) == 1
    assert version["proposal_status"] == "queued"

    # The read model: server totals, the source and the run number.
    view = estimate(client, headers, opp["id"])
    assert (view["version"]["source"], view["version"]["source_run"]) == ("assessments", 1)
    assert view["version"]["totals"]["effort_hours"] == 42.0
    assert view["version"]["totals"]["role_hours"] == {
        "engineer": 32.1,
        "project_manager": 9.9,
        "qa": 0.0,
    }
    assert view["assessment_running"] is False
    assert [s["section"] for s in view["version"]["sections"]] == ["functional", "integration"]


def test_a_task_retry_builds_a_new_version_for_the_same_run(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(
        AgentGateway(
            replies(
                engineering_agent=[agent_out(effort("R1", 20))],
                pm_agent=[agent_out(effort("R1", 10))],
                security_agent=[ModelUnavailableError("down", error_code="connection")],
            )
        )
    )
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    (v1,) = versions(sync_engine, opp["id"])  # partially failed: still built
    assert [str(line["effort_hours"]) for line in line_rows(sync_engine, v1["id"])] == ["30.0"]

    fake.replies["security_agent"] = [agent_out(effort("R1", 4))]
    assert retry(client, headers, opp["id"], body["id"], "security_agent").status_code == 201
    assert drain(db_url, ASSESS) == ["succeeded"]

    old, new = versions(sync_engine, opp["id"])
    assert (old["status"], new["status"], str(new["source_run_id"])) == (
        "superseded",
        "draft",
        body["id"],
    )
    assert [str(line["effort_hours"]) for line in line_rows(sync_engine, new["id"])] == ["34.0"]
    assert estimate(client, headers, opp["id"])["version"]["source_run"] == 1


# --- superseding and carrying ---------------------------------------------------------------


def test_it_supersedes_a_model_draft_and_carries_assumptions_and_edits(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    draft_tests.requeue(db_url, opp["id"])  # a model draft from before Story 8.3
    gateway.replies = [
        lines_out(
            est_line("Connect to SAP.", ["R1"], effort=40.0),
            est_line("Operations", ["R2"], section="non_functional", effort=12.0),
        )
    ]
    assert drain(db_url, DRAFT) == ["succeeded"]
    gateway.replies = [by_title(condition("WMS version unknown"))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    view = estimate(client, headers, opp["id"])
    (wms,) = view["version"]["assumptions"]["conditions"]
    accepted = client.post(
        f"{BASE}/{opp['id']}/assumptions/{wms['id']}/accept",
        headers={**headers, "If-Match": '"1"'},
    )
    assert accepted.status_code == 200, accepted.text
    edit(client, headers, opp["id"], lines_by_title(view)["Connect to SAP."])
    install(AgentGateway(HAPPY))

    run(client, headers, opp["id"], db_url)

    v1, v2 = versions(sync_engine, opp["id"])
    assert (v1["source"], v1["status"]) == ("model", "superseded")
    assert (v2["source"], v2["status"]) == ("assessments", "draft")
    after = estimate(client, headers, opp["id"])
    (carried,) = after["version"]["assumptions"]["conditions"]
    assert (carried["origin"]["title"], carried["carried_from_version"]) == (
        "WMS version unknown",
        1,
    )
    assert carried["accepted_by"] is not None
    sap = lines_by_title(after)["Connect to SAP."]
    assert (sap["effort_hours"], sap["edited"], sap["edit_carried_from_version"]) == (
        32.0,
        True,
        1,
    )
    assert sap["edit_reason"] == "Reuse the existing connector"
    assert after["version"]["totals"]["effort_hours"] == 40.0  # 32 h carried + 8 h
    (_, event) = created_events(sync_engine, opp["id"])
    assert (
        event["payload"]["carried_assumption_count"],
        event["payload"]["carried_edit_count"],
        event["payload"]["superseded_count"],
    ) == (1, 1, 1)


# --- Conflicts ------------------------------------------------------------------------------


def test_the_new_version_resolves_an_effort_conflict_in_the_same_finish(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    draft_tests.requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1"], effort=5.0))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    fake = install(AgentGateway(HAPPY))
    with monkeypatch.context() as before_8_3:  # a run finished before Story 8.3: no build

        async def no_build(*_: Any) -> None:
            return None

        before_8_3.setattr(estimates_public, "build_from_assessments", no_build)
        run(client, headers, opp["id"], db_url)
    (effort_conflict,) = [
        c for c in open_conflicts(sync_engine, opp["id"]) if c["type"] == "effort"
    ]
    assert len(versions(sync_engine, opp["id"])) == 1

    provider.install(fake)
    run(client, headers, opp["id"], db_url)

    # R1's Estimate line is now the agents' 34 h; only R3's scope Conflict (PM left it
    # unsized) is still open.
    assert [c["type"] for c in open_conflicts(sync_engine, opp["id"])] == ["scope"]
    (resolved,) = rows(
        sync_engine, "SELECT * FROM conflicts_conflicts WHERE id = :i", i=effort_conflict["id"]
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolution_reason"].startswith("No longer present in")


def test_lines_with_an_open_conflict_are_marked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    # PM leaves R3 unsized (a scope Conflict on R3); Security doesn't proceed (an Opportunity-
    # level clash, which marks no line).
    install(
        AgentGateway(
            replies(
                engineering_agent=[
                    agent_out(effort("R1", 20), effort("R3", 8), recommendation="proceed")
                ],
                pm_agent=[agent_out(effort("R1", 10))],
                security_agent=[agent_out(recommendation="do_not_proceed")],
            )
        )
    )

    run(client, headers, opp["id"], db_url)

    conflicts = {c["type"]: c for c in open_conflicts(sync_engine, opp["id"])}
    assert set(conflicts) == {"scope", "assumption"}
    lines = lines_by_title(estimate(client, headers, opp["id"]))
    assert lines["Peak 900 orders/hour."]["conflicts"] == [
        {"id": str(conflicts["scope"]["id"]), "type": "scope"}
    ]
    assert lines["Connect to SAP."]["conflicts"] == []

    # The next run agrees: the marker goes with the Conflict.
    install(AgentGateway(HAPPY | {"pm_agent": [agent_out(effort("R1", 10), effort("R3", 2))]}))
    run(client, headers, opp["id"], db_url)
    lines = lines_by_title(estimate(client, headers, opp["id"]))
    assert all(line["conflicts"] == [] for line in lines.values())


# --- nothing to build -----------------------------------------------------------------------


def test_a_run_with_no_succeeded_task_builds_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(HAPPY))
    run(client, headers, opp["id"], db_url)
    (before,) = versions(sync_engine, opp["id"])
    down = ModelUnavailableError("down", error_code="connection")
    fake.replies = {agent: [down] for agent in fake.replies}

    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    assert run_rows(sync_engine, opp["id"])[-1]["status"] == "failed"
    (after,) = versions(sync_engine, opp["id"])
    assert (after["id"], after["status"], after["row_version"]) == (
        before["id"],
        "draft",
        before["row_version"],
    )
    assert len(created_events(sync_engine, opp["id"])) == 1


def test_assessments_that_size_no_active_requirement_build_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(replies(**{a: [agent_out()] for a in HAPPY})))

    run(client, headers, opp["id"], db_url)

    assert run_rows(sync_engine, opp["id"])[-1]["status"] == "succeeded"
    assert versions(sync_engine, opp["id"]) == []
    assert created_events(sync_engine, opp["id"]) == []
    view = estimate(client, headers, opp["id"])
    assert (view["version"], view["assessment_running"]) == (None, False)


# --- the model path, kept but not triggered -------------------------------------------------


def test_a_late_model_draft_stores_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    draft_tests.requeue(db_url, opp["id"])  # left over from before Story 8.3
    fake = install(AgentGateway(HAPPY))
    run(client, headers, opp["id"], db_url)
    provider.install(gateway)
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1"]))]

    assert drain(db_url, DRAFT) == ["succeeded"]

    (only,) = versions(sync_engine, opp["id"])
    assert (only["source"], only["status"]) == ("assessments", "draft")
    (draft,) = rows(
        sync_engine, "SELECT * FROM estimates_drafts WHERE opportunity_id = :o", o=opp["id"]
    )
    assert draft["status"] == "succeeded"
    assert fake.calls("engineering_agent") == 1


# --- the read model's waiting state ---------------------------------------------------------


def test_the_estimate_says_a_run_is_in_progress_until_it_finishes(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    assert estimate(client, headers, opp["id"])["assessment_running"] is False
    install(AgentGateway(HAPPY))

    started(client, headers, opp["id"])

    waiting = estimate(client, headers, opp["id"])
    assert (waiting["version"], waiting["assessment_running"]) == (None, True)
    assert drain(db_url, ASSESS) == ["succeeded"]
    done = estimate(client, headers, opp["id"])
    assert done["assessment_running"] is False
    assert done["version"]["source"] == "assessments"


def test_a_model_version_reads_as_from_the_model(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    draft_tests.requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]

    version = estimate(client, headers, opp["id"])["version"]

    assert (version["source"], version["source_run"]) == ("model", None)
    assert all(line["conflicts"] == [] for s in version["sections"] for line in s["lines"])
    (row,) = versions(sync_engine, opp["id"])
    assert (row["source"], row["source_run_id"]) == ("model", None)
    assert isinstance(row["id"], UUID)


def test_an_effort_conflict_marks_the_line_covering_its_requirement(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(HAPPY))
    run(client, headers, opp["id"], db_url)  # v1: R1 34 h
    edit(
        client,
        headers,
        opp["id"],
        lines_by_title(estimate(client, headers, opp["id"]))["Connect to SAP."],
        10,
    )

    run(client, headers, opp["id"], db_url)  # v2 carries the 10 h edit: an effort Conflict on R1

    (effort_conflict,) = [
        c for c in open_conflicts(sync_engine, opp["id"]) if c["type"] == "effort"
    ]
    view = estimate(client, headers, opp["id"])
    assert (view["version"]["version"], view["version"]["source_run"]) == (2, 2)
    assert lines_by_title(view)["Connect to SAP."]["conflicts"] == [
        {"id": str(effort_conflict["id"]), "type": "effort"}
    ]


# --- a cancelled run ------------------------------------------------------------------------


def test_a_cancel_after_a_task_succeeded_builds_the_version_and_rechecks_conflicts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(
        AgentGateway(
            HAPPY
            | {"pm_agent": [agent_out(effort("R1", 10), effort("R3", 2), recommendation="proceed")]}
        )
    )
    run(client, headers, opp["id"], db_url)  # run 1: v1, no Conflict
    assert open_conflicts(sync_engine, opp["id"]) == []
    body = started(client, headers, opp["id"])
    _mid_run(sync_engine, body["id"])
    _accept(
        db_url,
        body["id"],
        AssessmentAgent.ENGINEERING,
        agent_out(effort("R1", 40), effort("R3", 8), recommendation="do_not_proceed"),
        _inputs(sync_engine, opp["id"]),
    )

    response = cancel(client, headers, opp["id"], body["id"])

    assert response.status_code == 200, response.text
    v1, v2 = versions(sync_engine, opp["id"])
    assert (v1["status"], v2["status"], str(v2["source_run_id"])) == (
        "superseded",
        "draft",
        body["id"],
    )
    view = estimate(client, headers, opp["id"])
    assert view["version"]["source_run"] == 2
    assert lines_by_title(view)["Connect to SAP."]["effort_hours"] == 54.0  # 40 + 10 + 4
    # Detection ran for the cancelled run: Engineering's new do_not_proceed clashes with PM.
    (clash,) = open_conflicts(sync_engine, opp["id"])
    assert (clash["type"], str(clash["run_id"])) == ("assumption", body["id"])


def test_a_cancel_with_no_succeeded_task_builds_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    body = started(client, headers, opp["id"])
    _mid_run(sync_engine, body["id"])

    response = cancel(client, headers, opp["id"], body["id"])

    assert response.status_code == 200, response.text
    assert versions(sync_engine, opp["id"]) == []
    assert created_events(sync_engine, opp["id"]) == []
    assert (
        rows(
            sync_engine, "SELECT * FROM conflicts_conflicts WHERE opportunity_id = :o", o=opp["id"]
        )
        == []
    )
