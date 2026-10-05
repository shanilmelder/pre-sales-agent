"""Red Team Reviews (Story 6.5) against a real, migrated Postgres as psa_app: auto-queueing on
an accepted Estimate draft, coalescing, the `assessments.red_team_review` job with a fake
ModelGateway, `accept_red_team_review` (validation, versions, links, trace), failures and the
table grants.

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no
other claimer takes them, and `drain` runs only the current test's Opportunities' jobs.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.agents.contract import AgentResult
from app.agents.red_team_agent.agent import prompt
from app.agents.red_team_agent.schema import RedTeamOutput
from app.modules.assessments.application import public as assessments
from app.modules.assessments.application import review as assessments_review
from app.platform.actor import Actor
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredRequest,
)
from app.platform.uow import unit_of_work
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_estimates_draft import SIX, detected, est_line, lines_out, versions
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_intake_extraction import DRAFT, RED_TEAM, FakeGateway, drain, owner

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile


@pytest.fixture(autouse=True)
def _review_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assessments_review, "review_settings", lambda: Settings(model_profile_chat="demo-chat")
    )


def finding(
    title: str,
    requirements: list[str],
    *,
    category: str = "integration_harder",
    severity: str = "high",
    lines: list[str] | None = None,
    argument: str | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "argument": argument or f"Nothing shows {title.lower()} is understood.",
        "requirements": requirements,
        "lines": lines or [],
    }


def _line_labels(request: StructuredRequest[Any]) -> dict[str, str]:
    """`{title: label}` of the LINE data blocks in the request's user message."""
    user = request.messages[1].content
    return {
        title: label for label, title in re.findall(r"<<<LINE (L\d+) [^\n]*>>>\n([^\n]*)\n", user)
    }


def findings_out(*items: Mapping[str, Any]) -> Callable[[StructuredRequest[Any]], RedTeamOutput]:
    """A reply whose `lines` name Estimate lines by title, resolved to the labels the request
    gave them (unknown titles are passed through as labels)."""

    def reply(request: StructuredRequest[Any]) -> RedTeamOutput:
        labels = _line_labels(request)
        out = []
        for item in items:
            entry = dict(item)
            entry["lines"] = [labels.get(t, t) for t in entry.get("lines", [])]
            out.append(entry)
        return RedTeamOutput.model_validate({"findings": out})

    return reply


def drafted(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, count: int = 5
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with `count` Requirements, its Gaps detected, its Estimate drafted (the
    SIX lines, or one line per Requirement when fewer) and its Red Team Review queued."""
    headers, opp = detected(client, engine, db_url, gateway, count=count)
    if count == 5:
        gateway.replies = [lines_out(*SIX)]
    else:
        gateway.replies = [
            lines_out(*(est_line(f"Item {n}", [f"R{n}"]) for n in range(1, count + 1)))
        ]
    assert drain(db_url, DRAFT) == ["succeeded"]
    return headers, opp


def runs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_red_team_runs WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def review_jobs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o "
        "ORDER BY created_at, id",
        t=RED_TEAM,
        o=opp_id,
    )


def reviews(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_reviews WHERE opportunity_id = :o ORDER BY version",
        o=opp_id,
    )


def finding_rows(engine: Engine, review_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_findings WHERE review_id = :r ORDER BY position",
        r=review_id,
    )


def requirement_links(engine: Engine, finding_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_finding_requirements WHERE finding_id = :f",
        f=finding_id,
    )


def line_links(engine: Engine, finding_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine, "SELECT * FROM assessments_finding_lines WHERE finding_id = :f", f=finding_id
    )


def events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type LIKE 'assessments.%' "
        "AND event_type NOT LIKE 'assessments.assessment_run.%' ORDER BY occurred_at, id",
        o=opp_id,
    )


def estimate_lines(engine: Engine, opp_id: str) -> dict[str, Any]:
    """`{title: line id}` of the Opportunity's current draft Estimate Version."""
    (version,) = [v for v in versions(engine, opp_id) if v["status"] == "draft"]
    return {r["title"]: r["id"] for r in draft_tests.line_rows(engine, version["id"])}


def requeue(db_url: str, opp_id: str) -> None:
    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await assessments.enqueue_review(uow, UUID(opp_id))
        finally:
            await engine.dispose()

    run_async(scenario())


FIVE = (
    finding(
        "SAP custom fields — no evidence the IDoc mapping covers them",
        ["R1"],
        severity="medium",
        lines=["SAP order interface"],
    ),
    finding(
        "Single sign-on — identity provider not named",
        ["R4"],
        category="hidden_dependency",
        severity="low",
    ),
    finding(
        "Peak 900 orders/hour — no seasonal profile",
        ["R3"],
        category="requirement_incomplete",
        severity="critical",
        lines=["Order throughput", "Project management"],
    ),
    finding(
        "24/7 support — no on-call model priced",
        ["R2"],
        category="capability_overstated",
        severity="high",
    ),
    finding(
        "EUR pricing — currency risk on imported hardware",
        ["R5", "R1"],
        category="hidden_dependency",
        severity="medium",
    ),
)


# --- queueing -------------------------------------------------------------------------------


def test_an_accepted_draft_queues_one_review_in_the_same_transaction(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    assert runs(sync_engine, opp["id"]) == []  # nothing before the draft
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1", "R2"]))]

    assert drain(db_url, DRAFT) == ["succeeded"]

    (run,) = runs(sync_engine, opp["id"])
    (job,) = review_jobs(sync_engine, opp["id"])
    assert job["payload"] == {"run_id": str(run["id"])}
    assert (job["status"], job["priority"]) == ("queued", 1)  # background
    assert (run["status"], run["error_code"], run["finished_at"]) == ("queued", None, None)


def test_a_failed_draft_queues_no_review(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [ModelUnavailableError("down")]

    assert drain(db_url, DRAFT) == ["failed_retrying", "dead"]

    assert runs(sync_engine, opp["id"]) == []


def test_drafts_while_one_review_waits_coalesce(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    draft_tests.requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("Everything", ["R1", "R2"]))]

    assert drain(db_url, DRAFT) == ["succeeded"]

    assert len(review_jobs(sync_engine, opp["id"])) == 1
    assert [r["status"] for r in runs(sync_engine, opp["id"])] == ["queued"]


def test_the_worker_loads_the_review_job_type() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[RED_TEAM]
    assert (spec.priority, spec.timeout_s, spec.max_attempts) == ("background", 900.0, 2)


# --- the happy path -------------------------------------------------------------------------


def test_a_review_stores_v1_with_ranked_findings_links_and_one_event(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    lines = estimate_lines(sync_engine, opp["id"])
    (estimate,) = versions(sync_engine, opp["id"])
    gateway.replies = [findings_out(*FIVE)]

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, RED_TEAM) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    assert (review["version"], review["kind"], review["status"]) == (1, "red_team", "current")
    assert (review["estimate_version_id"], review["dropped_count"]) == (estimate["id"], 0)
    stored = finding_rows(sync_engine, review["id"])
    assert [(r["position"], r["title"]) for r in stored] == [
        (n, item["title"]) for n, item in enumerate(FIVE, start=1)
    ]
    peak = stored[2]
    assert (peak["category"], peak["severity"]) == ("requirement_incomplete", "critical")
    assert (
        peak["argument"]
        == "Nothing shows peak 900 orders/hour — no seasonal profile is understood."
    )
    (link,) = requirement_links(sync_engine, peak["id"])
    assert (link["requirement_id"], link["requirement_version"]) == (reqs[2]["id"], 1)
    assert {r["line_id"] for r in line_links(sync_engine, peak["id"])} == {
        lines["Order throughput"],
        lines["Project management"],
    }
    assert [r["line_id"] for r in line_links(sync_engine, stored[0]["id"])] == [
        lines["SAP order interface"]
    ]
    assert line_links(sync_engine, stored[1]["id"]) == []
    assert {r["requirement_id"] for r in requirement_links(sync_engine, stored[4]["id"])} == {
        reqs[0]["id"],
        reqs[4]["id"],
    }
    (run,) = runs(sync_engine, opp["id"])
    assert (run["status"], run["error_code"]) == ("succeeded", None)
    assert run["finished_at"] is not None

    (event,) = events(sync_engine, opp["id"])
    assert event["event_type"] == "assessments.red_team_review.completed"
    assert (event["subject_type"], event["subject_id"]) == ("assessments.review", review["id"])
    assert (event["actor_type"], event["actor_id"]) == ("agent", "red_team_agent@0.1.0")
    assert event["payload"] == {
        "version": 1,
        "finding_count": 5,
        "critical_count": 1,
        "high_count": 1,
        "medium_count": 2,
        "low_count": 1,
        "dropped_count": 0,
        "requirement_count": 5,
        "gap_count": 1,
        "line_count": 6,
        "superseded_count": 0,
    }

    # One model call: instructions as the system message; Requirements, Gaps and lines only
    # as data blocks.
    request = gateway.requests[-1]
    system, user = request.messages
    assert (system.role, system.content) == ("system", prompt())
    assert "<<<REQUIREMENT R1 classification=integration token=" in user.content
    assert "<<<REQUIREMENT R5 classification=commercial token=" in user.content
    assert "<<<GAP G1 category=integration_details impact=high token=" in user.content
    assert "<<<LINE L1 section=functional effort_hours=24.5 token=" in user.content
    assert "Prices in EUR." in user.content
    assert request.caller.agent_id == "red_team_agent"
    assert request.caller.run_id == run["id"]
    assert (request.profile, request.priority) == ("demo-chat", "background")
    assert request.output_model is RedTeamOutput

    # Privacy: no Requirement, Gap or Finding text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    trace_text = str(events(sync_engine, opp["id"]))
    for leak in (
        "SAP",
        "EUR",
        "sign-on",
        "Single sign-on",
        "seasonal",
        "Nothing shows",
        "interface type",
        "Order throughput",
    ):
        assert leak not in logged
        assert leak not in trace_text


def test_an_unknown_line_label_is_ignored_and_the_finding_kept(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [findings_out(finding("Uptime claim", ["R2"], lines=["L99"]))]

    assert drain(db_url, RED_TEAM) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    (row,) = finding_rows(sync_engine, review["id"])
    assert row["title"] == "Uptime claim"
    assert line_links(sync_engine, row["id"]) == []
    assert len(requirement_links(sync_engine, row["id"])) == 1
    assert review["dropped_count"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        finding("Unknown label", ["R99"]),
        finding("Gap label", ["G1"]),
        finding("Unknown category", ["R1"], category="vague"),
        finding("Unknown severity", ["R1"], severity="urgent"),
        finding("", ["R1"]),
        finding("Long title" * 20, ["R1"]),
        finding("Long argument", ["R1"], argument="x" * 801),
        finding("No requirements", []),
    ],
    ids=["label", "gap-label", "category", "severity", "blank", "title", "argument", "none"],
)
def test_an_invalid_finding_is_dropped_and_counted(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    bad: dict[str, Any],
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [findings_out(finding("SAP custom fields", ["R1"]), bad)]

    assert drain(db_url, RED_TEAM) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    assert [r["title"] for r in finding_rows(sync_engine, review["id"])] == ["SAP custom fields"]
    assert review["dropped_count"] == 1
    assert events(sync_engine, opp["id"])[0]["payload"]["dropped_count"] == 1


def test_when_every_finding_is_invalid_twice_the_review_fails(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway)
    requests_before = len(gateway.requests)
    gateway.replies = [
        findings_out(finding("Bad label", ["R99"]), finding("Bad enum", ["R1"], severity="?"))
    ]

    assert drain(db_url, RED_TEAM, max_runs=1) == ["failed_retrying"]
    assert runs(sync_engine, opp["id"])[0]["status"] == "running"
    assert drain(db_url, RED_TEAM) == ["dead"]

    (run,) = runs(sync_engine, opp["id"])
    assert (run["status"], run["error_code"]) == ("failed", "output_invalid")
    assert len(gateway.requests) == requests_before + 2  # one call per attempt
    assert reviews(sync_engine, opp["id"]) == []
    (job,) = review_jobs(sync_engine, opp["id"])
    assert (job["status"], job["attempts"]) == ("dead", 2)
    assert "Bad label" not in str(job["last_error"])
    assert events(sync_engine, opp["id"]) == []


def test_a_redraft_is_reviewed_again_and_supersedes_the_earlier_review(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [findings_out(*FIVE)]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    draft_tests.requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("Everything", ["R1", "R2", "R3", "R4", "R5"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]  # the re-draft queues a second review
    assert [r["status"] for r in runs(sync_engine, opp["id"])] == ["succeeded", "queued"]
    gateway.replies = [
        findings_out(finding("One estimate line for everything", ["R1"], lines=["Everything"]))
    ]

    assert drain(db_url, RED_TEAM) == ["succeeded"]

    v1, v2 = reviews(sync_engine, opp["id"])
    assert (v1["version"], v1["status"]) == (1, "superseded")
    assert (v2["version"], v2["status"]) == (2, "current")
    assert len(finding_rows(sync_engine, v1["id"])) == 5  # kept, read-only
    assert [r["title"] for r in finding_rows(sync_engine, v2["id"])] == [
        "One estimate line for everything"
    ]
    estimate = next(v for v in versions(sync_engine, opp["id"]) if v["status"] == "draft")
    assert v2["estimate_version_id"] == estimate["id"]
    completed = [e["payload"] for e in events(sync_engine, opp["id"])]
    assert [(p["version"], p["superseded_count"]) for p in completed] == [(1, 0), (2, 1)]


def test_with_no_active_requirements_nothing_is_asked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    requeue(db_url, opp["id"])
    gateway.replies = [ModelUnavailableError("must not be called")]

    assert drain(db_url, RED_TEAM) == ["succeeded"]

    assert gateway.requests == []
    assert runs(sync_engine, opp["id"])[0]["status"] == "succeeded"
    assert reviews(sync_engine, opp["id"]) == []


def test_without_an_estimate_the_requirements_are_still_reviewed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    requeue(db_url, opp["id"])
    gateway.replies = [findings_out(finding("SAP custom fields", ["R1"], lines=["L1"]))]

    assert drain(db_url, RED_TEAM) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    assert review["estimate_version_id"] is None
    (row,) = finding_rows(sync_engine, review["id"])
    assert line_links(sync_engine, row["id"]) == []
    assert "<<<LINE" not in gateway.requests[-1].messages[1].content


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelUnavailableError("down", error_code="connection"), "model_unavailable"),
        (ModelTimeoutError("slow"), "model_timeout"),
        (ModelOutputInvalidError("cut", error_code="truncated"), "output_invalid"),
    ],
)
def test_a_gateway_error_retries_then_fails_the_review(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    error: Exception,
    code: str,
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [error]

    assert drain(db_url, RED_TEAM) == ["failed_retrying", "dead"]

    (run,) = runs(sync_engine, opp["id"])
    assert (run["status"], run["error_code"]) == ("failed", code)
    assert run["finished_at"] is not None
    assert reviews(sync_engine, opp["id"]) == []


def _inputs(engine: Engine, opp_id: str) -> assessments_review.ReviewInputs:
    return assessments_review.ReviewInputs(
        requirements=[
            assessments_review.ReviewRequirement(
                label=f"R{n}",
                requirement_id=r["id"],
                version=r["version"],
                classification=r["classification"],
                text=r["text"],
            )
            for n, r in enumerate(requirement_rows(engine, opp_id), start=1)
        ]
    )


def _accept(
    db_url: str, run_id: Any, output: RedTeamOutput, inputs: assessments_review.ReviewInputs
) -> None:
    result = AgentResult(
        confidence=0.5,
        confidence_basis="test",
        needs_human_review=True,
        extensions={"red_team_agent": output},
    )

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await assessments_review.accept_red_team_review(
                    uow,
                    run_id=run_id,
                    result=result,
                    inputs=inputs,
                    actor=Actor(type="agent", id="red_team_agent@0.1.0"),
                )
        finally:
            await engine.dispose()

    run_async(scenario())


def _out(*items: dict[str, Any]) -> RedTeamOutput:
    return RedTeamOutput.model_validate({"findings": list(items)})


def test_an_older_run_accepted_after_a_newer_one_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    (older,) = runs(sync_engine, opp["id"])
    inputs = _inputs(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the older run is mid-call; its job is out of the way
        conn.execute(
            sa.text("UPDATE assessments_red_team_runs SET status = 'running' WHERE id = :r"),
            {"r": older["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead' WHERE opportunity_id = :o "
                "AND job_type = :t"
            ),
            {"o": opp["id"], "t": RED_TEAM},
        )
    requeue(db_url, opp["id"])
    gateway.replies = [findings_out(finding("Newer", ["R1"]))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]  # the newer run

    _accept(db_url, older["id"], _out(), inputs)  # empty: invalid if it were current

    (review,) = reviews(sync_engine, opp["id"])
    assert [r["title"] for r in finding_rows(sync_engine, review["id"])] == ["Newer"]
    assert len(events(sync_engine, opp["id"])) == 1
    assert runs(sync_engine, opp["id"])[0]["status"] == "succeeded"


def test_a_requirement_changed_after_the_read_does_not_resolve(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    (run,) = runs(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the run has read the Requirements and is mid-call
        conn.execute(
            sa.text("UPDATE assessments_red_team_runs SET status = 'running' WHERE id = :r"),
            {"r": run["id"]},
        )
    inputs = _inputs(sync_engine, opp["id"])
    reqs = requirement_rows(sync_engine, opp["id"])
    edited = client.patch(
        f"{extraction_tests.BASE}/{opp['id']}/requirements/{reqs[0]['id']}",
        headers={**headers, "If-Match": f'"{reqs[0]["row_version"]}"'},
        json={"text": "Connect to SAP EWM over IDocs."},
    )
    assert edited.status_code == 200, edited.text

    _accept(db_url, run["id"], _out(finding("SAP", ["R1"]), finding("Uptime", ["R2"])), inputs)

    (review,) = reviews(sync_engine, opp["id"])
    assert [r["title"] for r in finding_rows(sync_engine, review["id"])] == ["Uptime"]
    assert review["dropped_count"] == 1


def test_findings_and_links_are_insert_only_and_nothing_is_deletable_for_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [findings_out(finding("SAP custom fields", ["R1"], lines=["Item 1"]))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    (review,) = reviews(sync_engine, opp["id"])
    (row,) = finding_rows(sync_engine, review["id"])
    assert len(line_links(sync_engine, row["id"])) == 1
    denied = [
        ("UPDATE assessments_findings SET title = 'x' WHERE id = :i", row["id"]),
        ("DELETE FROM assessments_findings WHERE id = :i", row["id"]),
        (
            "UPDATE assessments_finding_requirements SET requirement_version = 9 "
            "WHERE finding_id = :i",
            row["id"],
        ),
        ("DELETE FROM assessments_finding_requirements WHERE finding_id = :i", row["id"]),
        (
            "UPDATE assessments_finding_lines SET line_id = finding_id WHERE finding_id = :i",
            row["id"],
        ),
        ("DELETE FROM assessments_finding_lines WHERE finding_id = :i", row["id"]),
        ("DELETE FROM assessments_reviews WHERE id = :i", review["id"]),
        ("DELETE FROM assessments_red_team_runs WHERE opportunity_id = :i", opp["id"]),
    ]
    for sql, value in denied:
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": value})


# --- review-style edges ---------------------------------------------------------------------


class _Hanging:
    async def complete_structured(self, request: StructuredRequest[Any]) -> Any:
        await asyncio.sleep(60)
        raise AssertionError("not reached")


@pytest.mark.parametrize(
    ("attempt", "status", "code"), [(2, "failed", "model_timeout"), (1, "running", None)]
)
def test_a_cancelled_run_is_recorded_as_timed_out_only_on_the_final_attempt(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    attempt: int,
    status: str,
    code: str | None,
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    (job,) = review_jobs(sync_engine, opp["id"])
    provider.install(_Hanging())

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=job["id"],
            job_type=RED_TEAM,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=UUID(opp["id"]),
            engine=engine,
        )
        payload = assessments_review.RedTeamReview.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(1):
                    await assessments_review.red_team_review(ctx, payload)
        finally:
            await engine.dispose()

    run_async(scenario())

    (run,) = runs(sync_engine, opp["id"])
    assert (run["status"], run["error_code"]) == (status, code)


def test_a_job_whose_run_is_no_longer_in_progress_is_skipped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    with sync_engine.begin() as conn:  # failed (e.g. as lost) while its job still waits
        conn.execute(
            sa.text(
                "UPDATE assessments_red_team_runs SET status = 'failed', "
                "error_code = 'model_timeout', finished_at = now() WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )
    (before,) = runs(sync_engine, opp["id"])
    requests_before = len(gateway.requests)
    gateway.replies = [ModelUnavailableError("must not be called")]

    assert drain(db_url, RED_TEAM) == ["succeeded"]

    assert len(gateway.requests) == requests_before
    assert runs(sync_engine, opp["id"]) == [before]
    assert reviews(sync_engine, opp["id"]) == []


def test_queueing_fails_a_lost_run_first(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, count=2)
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE assessments_red_team_runs SET created_at = now() - :age "
                "WHERE opportunity_id = :o"
            ),
            {"age": assessments_review.stale_after() * 2, "o": opp["id"]},
        )

    requeue(db_url, opp["id"])

    lost, new = runs(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert (new["status"], new["error_code"]) == ("queued", None)
    assert len(review_jobs(sync_engine, opp["id"])) == 2
