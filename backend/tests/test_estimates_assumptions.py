"""Assumptions (Story 8.4) against a real, migrated Postgres as psa_app: the
`estimates.propose_assumptions` job with a fake ModelGateway, `accept_assumption_proposals`
(validation, retry, Unconverted Gaps, trace), the Contingency arithmetic in the Estimate, and
accepting one or all Assumptions (If-Match, Gap conversion in the same transaction, 409, 412,
who may), plus Gap re-detection leaving converted Gaps alone; and a re-draft carrying the
accepted Assumptions forward (Story 8.7: line matching, proposals only for open Gaps).

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no other
claimer takes them, and `drain` runs only the current test's Opportunities' jobs.
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

from app.agents.estimating_agent.agent import named_prompt
from app.agents.estimating_agent.schema import AssumptionsOutput
from app.modules.estimates.application import assumptions as estimates_assumptions
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelUnavailableError, StructuredRequest
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_estimates_draft import SIX, est_line, lines_out, versions
from tests.test_gaps_detection import extracted, gap, gaps_out, rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, DRAFT, PROPOSE, FakeGateway, drain
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile


@pytest.fixture(autouse=True)
def _proposal_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        estimates_assumptions,
        "proposal_settings",
        lambda: Settings(model_profile_chat="demo-chat"),
    )


FOUR = (
    gap("WMS version unknown", ["R1"], impact="high"),
    gap("Peak order volume", ["R2"], category="data_volumes", impact="medium"),
    gap("SSO provider", ["R4"], category="security_and_compliance", impact="low"),
    gap("Test data owner", ["R3"], category="scope_and_ownership", impact="high"),
)


def _labels(request: StructuredRequest[Any], kind: str) -> dict[str, str]:
    """`{title: label}` of the GAP or LINE data blocks in the request's user message."""
    user = request.messages[1].content
    return {
        title: label
        for label, title in re.findall(rf"<<<{kind} ([GL]\d+) [^\n]*>>>\n([^\n]*)\n", user)
    }


def by_title(
    *items: Mapping[str, Any],
) -> Callable[[StructuredRequest[Any]], AssumptionsOutput]:
    """A reply that names Gaps and lines by title (`"gap"`, `"line"`), resolved to the labels
    the request gave them."""

    def reply(request: StructuredRequest[Any]) -> AssumptionsOutput:
        gaps = _labels(request, "GAP")
        lines = _labels(request, "LINE")
        out = []
        for item in items:
            entry = dict(item)
            entry["gap"] = gaps.get(entry["gap"], entry["gap"])
            if entry.get("line") is not None:
                entry["line"] = lines.get(entry["line"], entry["line"])
            out.append(entry)
        return AssumptionsOutput.model_validate({"assumptions": out})

    return reply


def condition(gap_title: str, wording: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "gap": gap_title,
        "kind": "condition",
        "wording": wording or f"The estimate assumes the customer settles {gap_title.lower()}.",
        **extra,
    }


def contingency(gap_title: str, hours: float | None, line: str | None = None) -> dict[str, Any]:
    return {
        "gap": gap_title,
        "kind": "contingency",
        "wording": f"Contingency for {gap_title.lower()}.",
        "hours": hours,
        "line": line,
    }


HAPPY = (
    condition("WMS version unknown"),
    contingency("Peak order volume", 8, line="24/7 operations"),  # L2
    condition("SSO provider"),
    contingency("Test data owner", 12),
)


def drafted(
    client: TestClient,
    engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    found: tuple[dict[str, Any], ...] = FOUR,
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with 5 Requirements, the Gaps `found`, a draft Estimate v1 of the SIX
    lines, and its Assumption proposals queued."""
    headers, opp = extracted(client, engine, db_url, gateway)
    gateway.replies = [gaps_out(*found)]
    assert drain(db_url, DETECT) == ["succeeded"]
    gateway.replies = [lines_out(*SIX)]
    assert drain(db_url, DRAFT) == ["succeeded"]
    return headers, opp


def proposed(
    client: TestClient,
    engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    *items: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    headers, opp = drafted(client, engine, db_url, gateway)
    gateway.replies = [by_title(*(items or HAPPY))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    return headers, opp


def assumption_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT a.* FROM estimates_assumptions a JOIN estimates_estimate_versions v "
        "ON v.id = a.version_id WHERE v.opportunity_id = :o ORDER BY v.version, a.position",
        o=opp_id,
    )


def gap_rows(engine: Engine, opp_id: str) -> dict[str, dict[str, Any]]:
    found = rows(engine, "SELECT * FROM gaps_gaps WHERE opportunity_id = :o", o=opp_id)
    return {g["title"]: g for g in found}


def events(engine: Engine, opp_id: str, *types: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = ANY(:t) ORDER BY occurred_at, id",
        o=opp_id,
        t=list(types),
    )


def _estimate(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/estimate", headers=headers)


def _accept(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    assumption_id: str,
    row_version: int | None = 1,
) -> Any:
    extra = {} if row_version is None else {"If-Match": f'"{row_version}"'}
    return client.post(
        f"{BASE}/{opp_id}/assumptions/{assumption_id}/accept", headers={**headers, **extra}
    )


def _accept_all(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/assumptions/accept-all", headers=headers)


def _register(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    version: dict[str, Any] = _estimate(client, headers, opp_id).json()["version"]
    return version


def _all(version: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`{origin Gap title: Assumption}`."""
    groups = version["assumptions"]
    return {a["origin"]["title"]: a for a in groups["conditions"] + groups["contingencies"]}


# --- queueing -------------------------------------------------------------------------------


def test_an_accepted_draft_queues_its_proposals(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)

    (version,) = versions(sync_engine, opp["id"])
    assert version["proposal_status"] == "queued"
    (job,) = rows(
        sync_engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
        t=PROPOSE,
        o=opp["id"],
    )
    assert job["payload"] == {"version_id": str(version["id"])}
    assert (job["status"], job["priority"]) == ("queued", 1)  # background
    body = _register(client, headers, opp["id"])
    assert body["proposal_status"] == "queued"
    assert body["unconverted_gaps"] == []  # not before the proposals finish
    assert body["counts"] == {"total": 0, "accepted": 0, "not_accepted": 0}


def test_the_worker_loads_the_proposal_job_type() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[PROPOSE]
    assert (spec.priority, spec.timeout_s, spec.max_attempts) == ("background", 900.0, 2)


# --- proposals ------------------------------------------------------------------------------


def test_proposals_are_stored_unaccepted_and_priced_into_the_totals(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [by_title(*HAPPY)]  # type: ignore[list-item]

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, PROPOSE) == ["succeeded"]

    (version,) = versions(sync_engine, opp["id"])
    assert version["proposal_status"] == "succeeded"
    stored = assumption_rows(sync_engine, opp["id"])
    gaps = gap_rows(sync_engine, opp["id"])
    assert len(stored) == 4
    assert all(a["accepted_by"] is None and a["accepted_at"] is None for a in stored)
    assert all(a["row_version"] == 1 for a in stored)
    by_gap = {a["origin_ref"]["id"]: a for a in stored}
    peak = by_gap[str(gaps["Peak order volume"]["id"])]
    assert (peak["kind"], str(peak["amount_hours"])) == ("contingency", "8.0")
    assert peak["origin_ref"] == {
        "kind": "gap",
        "id": str(gaps["Peak order volume"]["id"]),
        "row_version": 1,
    }
    wms = by_gap[str(gaps["WMS version unknown"]["id"])]
    assert (wms["kind"], wms["amount_hours"], wms["line_id"]) == ("condition", None, None)
    assert wms["wording"] == "The estimate assumes the customer settles wms version unknown."
    owner_gap = by_gap[str(gaps["Test data owner"]["id"])]
    assert (str(owner_gap["amount_hours"]), owner_gap["line_id"]) == ("12.0", None)
    assert {g["status"] for g in gaps.values()} == {"open"}  # nothing converts until accepted

    (event,) = events(sync_engine, opp["id"], "estimates.assumption.proposed")
    assert (event["actor_type"], event["actor_id"]) == ("agent", "estimating_agent@0.1.0")
    assert (event["subject_type"], event["subject_id"]) == (
        "estimates.estimate_version",
        version["id"],
    )
    assert event["payload"] == {
        "count": 4,
        "condition_count": 2,
        "contingency_count": 2,
        "dropped_count": 0,
        "duplicate_count": 0,
        "unconverted_count": 0,
    }

    body = _register(client, headers, opp["id"])
    lines = {line["title"]: line for s in body["sections"] for line in s["lines"]}
    ops = lines["24/7 operations"]
    assert (ops["effort_hours"], ops["contingency_hours"], ops["total_hours"]) == (
        16.0,
        8.0,
        24.0,
    )
    assert lines["SAP order interface"]["contingency_hours"] == 0.0
    nfr = next(s for s in body["sections"] if s["section"] == "non_functional")
    assert (nfr["subtotal"]["contingency_hours"], nfr["subtotal"]["total_hours"]) == (8.0, 24.0)
    assert body["unallocated_contingency_hours"] == 12.0
    assert body["totals"]["effort_hours"] == 108.5
    assert body["totals"]["contingency_hours"] == 20.0
    assert body["totals"]["total_hours"] == 128.5
    assert body["counts"] == {"total": 4, "accepted": 0, "not_accepted": 4}
    assert body["unconverted_gaps"] == []
    groups = body["assumptions"]
    assert groups["contingency_hours"] == 20.0
    assert sorted(a["origin"]["title"] for a in groups["conditions"]) == [
        "SSO provider",
        "WMS version unknown",
    ]
    peak_view = _all(body)["Peak order volume"]
    assert peak_view["line"] == {"id": ops["id"], "title": "24/7 operations"}
    assert peak_view["amount_hours"] == 8.0
    assert peak_view["origin_kind"] == "gap"
    assert peak_view["origin"]["impact"] == "medium"
    assert peak_view["origin"]["status"] == "open"
    assert (peak_view["accepted_by"], peak_view["accepted_at"]) == (None, None)
    assert _all(body)["Test data owner"]["line"] is None

    # One model call: the second prompt file, Gaps (with their questions) and lines as data.
    request = gateway.requests[-1]
    system, user = request.messages
    assert (system.role, system.content) == ("system", named_prompt("v1-assumptions"))
    assert re.search(r"<<<GAP G1 category=\w+ impact=high token=", user.content)
    assert "<<<LINE L2 section=non_functional effort_hours=16.0 token=" in user.content
    assert "Clarification Question:" in user.content
    assert request.output_model is AssumptionsOutput
    assert request.caller.run_id == version["id"]
    assert (request.profile, request.priority) == ("demo-chat", "background")

    # Privacy: no Gap, line or Assumption text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    trace = str(events(sync_engine, opp["id"], "estimates.assumption.proposed"))
    for leak in ("WMS version", "Peak order", "estimate assumes", "Contingency for", "24/7"):
        assert leak not in logged
        assert leak not in trace


def test_a_gap_skipped_twice_is_listed_as_unconverted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [by_title(*HAPPY[:2], HAPPY[3])]  # type: ignore[list-item]

    assert drain(db_url, PROPOSE) == ["failed_retrying", "succeeded"]

    assert len(gateway.requests) >= 2
    assert len(assumption_rows(sync_engine, opp["id"])) == 3
    body = _register(client, headers, opp["id"])
    gaps = gap_rows(sync_engine, opp["id"])
    assert body["unconverted_gaps"] == [
        {
            "id": str(gaps["SSO provider"]["id"]),
            "title": "SSO provider",
            "category": "security_and_compliance",
            "impact": "low",
        }
    ]
    assert body["counts"]["total"] == 3
    (event,) = events(sync_engine, opp["id"], "estimates.assumption.proposed")
    assert event["payload"]["unconverted_count"] == 1


def test_a_gap_skipped_once_is_proposed_on_the_retry(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [
        by_title(*HAPPY[:3]),  # type: ignore[list-item]
        by_title(*HAPPY),  # type: ignore[list-item]
    ]

    assert drain(db_url, PROPOSE) == ["failed_retrying", "succeeded"]

    assert len(assumption_rows(sync_engine, opp["id"])) == 4


def test_invalid_and_duplicate_proposals_are_dropped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [
        by_title(  # type: ignore[list-item]
            condition("WMS version unknown", hours=4),  # a Condition with hours
            contingency("Peak order volume", None),  # a Contingency without hours
            contingency("SSO provider", 0.4),  # below 0.5 h
            contingency("Test data owner", 2000),  # above 1,000 h
            condition("G99"),  # no such Gap
            contingency("Peak order volume", 5, line="L99"),  # no such line
            condition("SSO provider", wording=" "),  # blank wording
            condition("SSO provider", wording="x" * 501),  # too long
            contingency("Test data owner", 6.04, line="SAP order interface"),  # kept, 6.0
            contingency("Test data owner", 9),  # a second one for the same Gap
            condition("SSO provider", line="SAP order interface"),  # kept, the line ignored
        )
    ]

    assert drain(db_url, PROPOSE) == ["failed_retrying", "succeeded"]

    stored = assumption_rows(sync_engine, opp["id"])
    assert [(a["kind"], a["amount_hours"] and str(a["amount_hours"])) for a in stored] == [
        ("contingency", "6.0"),
        ("condition", None),
    ]
    assert stored[1]["line_id"] is None
    (event,) = events(sync_engine, opp["id"], "estimates.assumption.proposed")
    assert event["payload"] == {
        "count": 2,
        "condition_count": 1,
        "contingency_count": 1,
        "dropped_count": 8,
        "duplicate_count": 1,
        "unconverted_count": 2,
    }
    titles = {g["title"] for g in _register(client, headers, opp["id"])["unconverted_gaps"]}
    assert titles == {"WMS version unknown", "Peak order volume"}


def test_no_open_gaps_means_no_model_call(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway, found=())
    calls = len(gateway.requests)

    assert drain(db_url, PROPOSE) == ["succeeded"]

    assert len(gateway.requests) == calls
    (version,) = versions(sync_engine, opp["id"])
    assert version["proposal_status"] == "succeeded"
    assert assumption_rows(sync_engine, opp["id"]) == []


def test_a_version_with_proposals_is_skipped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = proposed(client, sync_engine, db_url, gateway)
    (version,) = versions(sync_engine, opp["id"])
    calls = len(gateway.requests)
    with sync_engine.begin() as conn:  # as if its job ran again
        conn.exec_driver_sql(
            "UPDATE estimates_estimate_versions SET proposal_status = 'queued' WHERE id = %s",
            (version["id"],),
        )

    async def enqueue_again() -> None:
        from app.platform.uow import unit_of_work

        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await estimates_assumptions.enqueue_proposals(
                    uow, version_id=version["id"], opportunity_id=UUID(opp["id"])
                )
        finally:
            await engine.dispose()

    run_async(enqueue_again())

    assert drain(db_url, PROPOSE) == ["succeeded"]

    assert len(gateway.requests) == calls
    assert len(assumption_rows(sync_engine, opp["id"])) == 4
    assert versions(sync_engine, opp["id"])[0]["proposal_status"] == "succeeded"


def test_a_model_failure_twice_marks_the_proposals_failed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [ModelUnavailableError("down")]

    assert drain(db_url, PROPOSE) == ["failed_retrying", "dead"]

    body = _register(client, headers, opp["id"])
    assert body["proposal_status"] == "failed"
    assert {g["title"] for g in body["unconverted_gaps"]} == {t["title"] for t in FOUR}


def redraft(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    db_url: str,
    gateway: FakeGateway,
    lines: tuple[dict[str, Any], ...] = SIX,
) -> None:
    """Re-draft the Estimate (the Retry API) with `lines`, storing a new draft version."""
    started = client.post(f"{BASE}/{opp_id}/estimate-drafts", headers=headers)
    assert started.status_code == 201, started.text
    gateway.replies = [lines_out(*lines)]
    assert drain(db_url, DRAFT) == ["succeeded"]


def _accept_two(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    """Accept WMS (a Condition) and Peak (8 h on "24/7 operations"); the v1 Register."""
    v1 = _all(_register(client, headers, opp_id))
    for title in ("WMS version unknown", "Peak order volume"):
        assert _accept(client, headers, opp_id, v1[title]["id"]).status_code == 200
    return _all(_register(client, headers, opp_id))


def _of(engine: Engine, opp_id: str, version_id: Any) -> list[dict[str, Any]]:
    return [a for a in assumption_rows(engine, opp_id) if a["version_id"] == version_id]


def test_a_redraft_carries_the_accepted_assumptions_forward(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    v1 = _accept_two(client, headers, opp["id"])
    v1_rows = {str(a["id"]): a for a in assumption_rows(sync_engine, opp["id"])}

    with caplog.at_level(logging.DEBUG):
        redraft(client, headers, opp["id"], db_url, gateway)

    first, second = versions(sync_engine, opp["id"])
    stored = _of(sync_engine, opp["id"], second["id"])
    assert len(stored) == 2  # only the accepted ones, before any proposal
    titles = ("WMS version unknown", "Peak order volume")
    for position, (title, copy) in enumerate(zip(titles, stored, strict=True), start=1):
        source = v1_rows[v1[title]["id"]]
        assert str(copy["carried_from"]) == v1[title]["id"]
        assert copy["id"] != source["id"]
        assert (copy["position"], copy["row_version"]) == (position, 1)
        for column in ("kind", "wording", "amount_hours", "origin_ref", "accepted_by"):
            assert copy[column] == source[column], column
        assert copy["accepted_at"] == source["accepted_at"]
    v2_lines = draft_tests.line_rows(sync_engine, second["id"])
    v2_ops = next(r for r in v2_lines if r["title"] == "24/7 operations")
    assert stored[1]["line_id"] == v2_ops["id"]  # matched, never the old line id
    assert stored[1]["line_id"] != v1_rows[v1["Peak order volume"]["id"]]["line_id"]

    created = events(sync_engine, opp["id"], "estimates.estimate_version.created")
    assert [e["payload"]["carried_assumption_count"] for e in created] == [0, 2]

    # The proposals then cover only the two Gaps still open, numbered after the carried.
    calls = len(gateway.requests)
    gateway.replies = [by_title(HAPPY[2], HAPPY[3])]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    assert len(gateway.requests) == calls + 1
    assert set(_labels(gateway.requests[-1], "GAP")) == {"SSO provider", "Test data owner"}
    stored = _of(sync_engine, opp["id"], second["id"])
    assert [a["position"] for a in stored] == [1, 2, 3, 4]
    assert [a["carried_from"] is not None for a in stored] == [True, True, False, False]

    body = _register(client, headers, opp["id"])
    assert body["version"] == 2
    assert body["counts"] == {"total": 4, "accepted": 2, "not_accepted": 2}
    assert body["unconverted_gaps"] == []
    view = _all(body)
    for title in titles:
        assert view[title]["carried_from_version"] == 1
        assert view[title]["accepted_by"] == v1[title]["accepted_by"]
        assert view[title]["accepted_at"] == v1[title]["accepted_at"]
        assert view[title]["origin"]["status"] == "converted"
    assert view["SSO provider"]["carried_from_version"] is None
    assert v1["WMS version unknown"]["carried_from_version"] is None
    # The carried 8 h is on v2's matching line, and counted once.
    lines = {line["title"]: line for s in body["sections"] for line in s["lines"]}
    assert view["Peak order volume"]["line"] == {
        "id": lines["24/7 operations"]["id"],
        "title": "24/7 operations",
    }
    assert lines["24/7 operations"]["contingency_hours"] == 8.0
    assert body["unallocated_contingency_hours"] == 12.0
    assert body["totals"]["contingency_hours"] == 20.0
    assert body["totals"]["total_hours"] == 128.5

    # Accept all leaves the carried ones alone.
    assert _accept_all(client, headers, opp["id"]).json() == {"count": 2}
    after = _of(sync_engine, opp["id"], second["id"])
    assert [a["row_version"] for a in after] == [1, 1, 2, 2]
    # The old version's Assumptions can't be accepted any more.
    old = _of(sync_engine, opp["id"], first["id"])[2]
    assert old["accepted_at"] is None
    assert _accept(client, headers, opp["id"], str(old["id"])).status_code == 404

    # Privacy: no wording in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    trace = str(created)
    for leak in ("estimate assumes", "Contingency for", "WMS version", "24/7"):
        assert leak not in logged
        assert leak not in trace


def test_a_second_redraft_carries_the_carried_assumptions_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    v1 = _accept_two(client, headers, opp["id"])
    v1_rows = {str(a["id"]): a for a in assumption_rows(sync_engine, opp["id"])}
    redraft(client, headers, opp["id"], db_url, gateway)
    _, second = versions(sync_engine, opp["id"])
    v2_rows = _of(sync_engine, opp["id"], second["id"])

    redraft(client, headers, opp["id"], db_url, gateway)

    _, _, third = versions(sync_engine, opp["id"])
    v3_rows = _of(sync_engine, opp["id"], third["id"])
    assert len(v3_rows) == 2
    titles = ("WMS version unknown", "Peak order volume")
    for title, v2_copy, v3_copy in zip(titles, v2_rows, v3_rows, strict=True):
        source = v1_rows[v1[title]["id"]]
        assert v3_copy["carried_from"] == v2_copy["id"]
        for column in ("wording", "origin_ref", "accepted_by", "accepted_at"):
            assert v3_copy[column] == source[column], column
    v3_ops = next(
        r
        for r in draft_tests.line_rows(sync_engine, third["id"])
        if r["title"] == "24/7 operations"
    )
    assert v3_rows[1]["line_id"] == v3_ops["id"]

    view = _all(_register(client, headers, opp["id"]))
    assert {view[t]["carried_from_version"] for t in titles} == {2}
    assert view["Peak order volume"]["line"]["id"] == str(v3_ops["id"])
    created = events(sync_engine, opp["id"], "estimates.estimate_version.created")
    assert created[2]["payload"]["carried_assumption_count"] == 2


def test_a_redraft_with_nothing_accepted_carries_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)

    redraft(client, headers, opp["id"], db_url, gateway)
    gateway.replies = [by_title(*HAPPY)]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]

    _, second = versions(sync_engine, opp["id"])
    stored = _of(sync_engine, opp["id"], second["id"])
    assert [(a["position"], a["carried_from"]) for a in stored] == [
        (1, None),
        (2, None),
        (3, None),
        (4, None),
    ]
    created = events(sync_engine, opp["id"], "estimates.estimate_version.created")
    assert [e["payload"]["carried_assumption_count"] for e in created] == [0, 0]
    body = _register(client, headers, opp["id"])
    assert body["counts"] == {"total": 4, "accepted": 0, "not_accepted": 4}


def test_a_carried_contingency_matches_its_line_by_section_and_title(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    _accept_two(client, headers, opp["id"])
    renamed = tuple(
        est_line("  24/7 OPERATIONS ", ["R2"], section="non_functional", effort=20.0)
        if line["title"] == "24/7 operations"
        else line
        for line in SIX
    )

    redraft(client, headers, opp["id"], db_url, gateway, renamed)

    body = _register(client, headers, opp["id"])
    lines = [line for s in body["sections"] for line in s["lines"]]
    ops = next(line for line in lines if "OPERATIONS" in line["title"])
    assert _all(body)["Peak order volume"]["line"]["id"] == ops["id"]
    assert (ops["effort_hours"], ops["contingency_hours"]) == (20.0, 8.0)
    assert body["unallocated_contingency_hours"] == 0.0  # Test data owner isn't carried
    assert body["totals"]["contingency_hours"] == 8.0


@pytest.mark.parametrize(
    "replacement",
    [
        # No line with that section and title (the same title in another section).
        (est_line("24/7 operations", ["R2"], section="functional", effort=16.0),),
        # Two lines match.
        (
            est_line("24/7 operations", ["R2"], section="non_functional", effort=16.0),
            est_line("24/7 Operations", ["R2"], section="non_functional", effort=4.0),
        ),
    ],
    ids=["none", "two"],
)
def test_a_carried_contingency_without_one_matching_line_is_unallocated(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    replacement: tuple[dict[str, Any], ...],
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    _accept_two(client, headers, opp["id"])
    lines = tuple(line for line in SIX if line["title"] != "24/7 operations") + replacement

    redraft(client, headers, opp["id"], db_url, gateway, lines)

    body = _register(client, headers, opp["id"])
    peak = _all(body)["Peak order volume"]
    assert (peak["line"], peak["carried_from_version"]) == (None, 1)
    assert all(line["contingency_hours"] == 0.0 for s in body["sections"] for line in s["lines"])
    assert body["unallocated_contingency_hours"] == 8.0
    assert body["totals"]["contingency_hours"] == 8.0  # counted once
    assert body["assumptions"]["contingency_hours"] == 8.0


def test_redetection_between_drafts_keeps_the_carried_origins(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    v1 = _accept_two(client, headers, opp["id"])
    detection_tests.requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("Uptime target", ["R2"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    gateway.replies = [lines_out(*SIX)]

    assert drain(db_url, DRAFT) == ["succeeded"]  # the detection queued a re-draft

    gaps = gap_rows(sync_engine, opp["id"])
    assert gaps["WMS version unknown"]["status"] == "converted"
    assert gaps["Peak order volume"]["status"] == "converted"
    gateway.replies = [by_title(condition("Uptime target"))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    assert set(_labels(gateway.requests[-1], "GAP")) == {"Uptime target"}
    body = _register(client, headers, opp["id"])
    view = _all(body)
    assert set(view) == {"WMS version unknown", "Peak order volume", "Uptime target"}
    for title in ("WMS version unknown", "Peak order volume"):
        assert view[title]["origin"]["id"] == v1[title]["origin"]["id"]
        assert view[title]["origin"]["status"] == "converted"
        assert view[title]["carried_from_version"] == 1
    assert body["counts"] == {"total": 3, "accepted": 2, "not_accepted": 1}
    assert body["unconverted_gaps"] == []


def test_a_failed_redraft_carries_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    _accept_two(client, headers, opp["id"])
    before = assumption_rows(sync_engine, opp["id"])
    started = client.post(f"{BASE}/{opp['id']}/estimate-drafts", headers=headers)
    assert started.status_code == 201, started.text
    invalid = lines_out(est_line("Nothing real", ["R99"]))
    gateway.replies = [invalid, invalid]

    assert drain(db_url, DRAFT) == ["failed_retrying", "dead"]

    (only,) = versions(sync_engine, opp["id"])
    assert (only["version"], only["status"]) == (1, "draft")
    assert assumption_rows(sync_engine, opp["id"]) == before
    body = _register(client, headers, opp["id"])
    assert (body["version"], body["counts"]["accepted"]) == (1, 2)


# --- accepting ------------------------------------------------------------------------------


def test_the_owner_accepts_an_assumption_and_its_gap_converts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    before = _register(client, headers, opp["id"])
    peak = _all(before)["Peak order volume"]

    resp = _accept(client, headers, opp["id"], peak["id"])

    assert resp.status_code == 200, resp.text
    assert resp.headers["ETag"] == '"2"'
    body = resp.json()
    assert body["accepted_by"]["name"] == "Owner Person"
    assert body["accepted_at"] is not None
    assert body["row_version"] == 2
    assert body["origin"]["status"] == "converted"
    gaps = gap_rows(sync_engine, opp["id"])
    assert (gaps["Peak order volume"]["status"], gaps["Peak order volume"]["converted_to"]) == (
        "converted",
        "contingency",
    )
    assert gaps["WMS version unknown"]["status"] == "open"
    stored = {str(a["id"]): a for a in assumption_rows(sync_engine, opp["id"])}[peak["id"]]
    assert str(stored["accepted_by"]) == body["accepted_by"]["id"]

    (accepted,) = events(sync_engine, opp["id"], "estimates.assumption.accepted")
    assert (accepted["actor_type"], accepted["actor_id"]) == ("user", body["accepted_by"]["id"])
    assert (accepted["subject_type"], str(accepted["subject_id"])) == (
        "estimates.assumption",
        peak["id"],
    )
    assert accepted["payload"] == {
        "version_id": before["id"],
        "kind": "contingency",
        "amount_hours": 8.0,
        "line_id": peak["line"]["id"],
        "gap_id": str(gaps["Peak order volume"]["id"]),
        "accepted_by": body["accepted_by"]["id"],
    }
    (converted,) = events(sync_engine, opp["id"], "gaps.gap.converted")
    assert str(converted["subject_id"]) == str(gaps["Peak order volume"]["id"])
    assert converted["payload"] == {"assumption_kind": "contingency", "row_version": 2}

    after = _register(client, headers, opp["id"])
    assert after["totals"] == before["totals"]  # accepted or not, it was already counted
    assert after["counts"] == {"total": 4, "accepted": 1, "not_accepted": 3}

    # Accepting it again changes nothing, whatever If-Match says.
    again = _accept(client, headers, opp["id"], peak["id"], row_version=1)
    assert again.status_code == 200
    assert again.json()["accepted_at"] == body["accepted_at"]
    assert len(events(sync_engine, opp["id"], "estimates.assumption.accepted")) == 1

    # The Gaps tab lists it after the open ones, converted to a Contingency.
    listed = client.get(f"{BASE}/{opp['id']}/gaps", headers=headers).json()["items"]
    assert [(g["title"], g["status"], g["converted_to"]) for g in listed][-1] == (
        "Peak order volume",
        "converted",
        "contingency",
    )
    assert [g["status"] for g in listed[:-1]] == ["open"] * 3


def test_accepting_fails_whole_when_the_gap_is_no_longer_open(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]
    with sync_engine.begin() as conn:  # converted elsewhere first
        conn.exec_driver_sql(
            "UPDATE gaps_gaps SET status = 'converted', converted_to = 'condition', "
            "row_version = row_version + 1 WHERE id = %s",
            (UUID(wms["origin"]["id"]),),
        )

    resp = _accept(client, headers, opp["id"], wms["id"])

    assert resp.status_code == 409
    assert_problem(resp.json(), 409, "gap_not_open")
    stored = {str(a["id"]): a for a in assumption_rows(sync_engine, opp["id"])}[wms["id"]]
    assert (stored["accepted_by"], stored["accepted_at"], stored["row_version"]) == (
        None,
        None,
        1,
    )
    assert events(sync_engine, opp["id"], "estimates.assumption.accepted") == []

    # Accept all is all or nothing too.
    resp = _accept_all(client, headers, opp["id"])
    assert resp.status_code == 409
    assert all(a["accepted_at"] is None for a in assumption_rows(sync_engine, opp["id"]))
    assert events(sync_engine, opp["id"], "gaps.gap.converted") == []


def test_accept_all_accepts_the_rest(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, colleague_id).status_code == 200
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]
    assert _accept(client, headers, opp["id"], wms["id"]).status_code == 200

    resp = _accept_all(client, colleague, opp["id"])

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 3}
    body = _register(client, headers, opp["id"])
    assert body["counts"] == {"total": 4, "accepted": 4, "not_accepted": 0}
    accepted_by = {t: a["accepted_by"]["name"] for t, a in _all(body).items()}
    assert accepted_by == {
        "WMS version unknown": "Owner Person",
        "Peak order volume": "Colleague",
        "SSO provider": "Colleague",
        "Test data owner": "Colleague",
    }
    gaps = gap_rows(sync_engine, opp["id"])
    assert {t: (g["status"], g["converted_to"]) for t, g in gaps.items()} == {
        "WMS version unknown": ("converted", "condition"),
        "Peak order volume": ("converted", "contingency"),
        "SSO provider": ("converted", "condition"),
        "Test data owner": ("converted", "contingency"),
    }
    assert len(events(sync_engine, opp["id"], "estimates.assumption.accepted")) == 4
    assert len(events(sync_engine, opp["id"], "gaps.gap.converted")) == 4
    # Nothing left: a second accept-all accepts nothing.
    assert _accept_all(client, headers, opp["id"]).json() == {"count": 0}


def test_a_stale_or_missing_if_match_is_refused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]

    stale = _accept(client, headers, opp["id"], wms["id"], row_version=7)
    missing = _accept(client, headers, opp["id"], wms["id"], row_version=None)

    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert_problem(missing.json(), 428, "if_match_required")
    assert all(a["accepted_at"] is None for a in assumption_rows(sync_engine, opp["id"]))
    assert gap_rows(sync_engine, opp["id"])["WMS version unknown"]["status"] == "open"


def test_who_may_accept(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]

    seen = _estimate(client, rep, opp["id"])
    assert seen.status_code == 200
    assert seen.json()["can_accept_assumptions"] is False
    assert seen.json()["version"]["counts"]["total"] == 4
    assert _estimate(client, headers, opp["id"]).json()["can_accept_assumptions"] is True
    assert_problem(_accept(client, rep, opp["id"], wms["id"]).json(), 403, "forbidden")
    assert_problem(_accept_all(client, rep, opp["id"]).json(), 403, "forbidden")
    assert_problem(_accept(client, reader, opp["id"], wms["id"]).json(), 403, "forbidden")
    assert_problem(_accept(client, outsider, opp["id"], wms["id"]).json(), 404, "not_found")
    unknown = "01a10891-875d-7f80-9921-65c3fbf28ecb"
    assert_problem(_accept(client, headers, opp["id"], unknown).json(), 404, "not_found")
    assert all(a["accepted_at"] is None for a in assumption_rows(sync_engine, opp["id"]))


def test_redetection_leaves_converted_gaps_alone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    peak = _all(_register(client, headers, opp["id"]))["Peak order volume"]
    assert _accept(client, headers, opp["id"], peak["id"]).status_code == 200
    detection_tests.requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("Uptime target", ["R2"]))]

    assert drain(db_url, DETECT) == ["succeeded"]

    gaps = gap_rows(sync_engine, opp["id"])
    assert (gaps["Peak order volume"]["status"], gaps["Peak order volume"]["row_version"]) == (
        "converted",
        2,
    )
    assert {t: g["status"] for t, g in gaps.items() if t != "Peak order volume"} == {
        "WMS version unknown": "superseded",
        "SSO provider": "superseded",
        "Test data owner": "superseded",
        "Uptime target": "open",
    }
    listed = client.get(f"{BASE}/{opp['id']}/gaps", headers=headers).json()["items"]
    assert [(g["title"], g["status"]) for g in listed] == [
        ("Uptime target", "open"),
        ("Peak order volume", "converted"),
    ]
    # An Assumption whose Gap was superseded can't be accepted.
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]
    assert wms["origin"]["status"] == "superseded"
    assert_problem(_accept(client, headers, opp["id"], wms["id"]).json(), 409, "gap_not_open")


def test_psa_app_cannot_delete_assumptions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = proposed(client, sync_engine, db_url, gateway)
    first = assumption_rows(sync_engine, opp["id"])[0]
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM estimates_assumptions WHERE id = :i"), {"i": first["id"]})


class _Hanging:
    async def complete_structured(self, request: StructuredRequest[Any]) -> Any:
        await asyncio.sleep(60)
        raise AssertionError("not reached")


@pytest.mark.parametrize(("attempt", "status"), [(2, "failed"), (1, "running")])
def test_a_cancelled_run_is_recorded_as_failed_only_on_the_final_attempt(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    attempt: int,
    status: str,
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    (job,) = rows(
        sync_engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
        t=PROPOSE,
        o=opp["id"],
    )
    provider.install(_Hanging())

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=job["id"],
            job_type=PROPOSE,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=UUID(opp["id"]),
            engine=engine,
        )
        payload = estimates_assumptions.ProposeAssumptions.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(1):
                    await estimates_assumptions.propose_assumptions(ctx, payload)
        finally:
            await engine.dispose()

    run_async(scenario())

    (version,) = versions(sync_engine, opp["id"])
    assert version["proposal_status"] == status
    body = _register(client, headers, opp["id"])
    if status == "failed":
        assert {g["title"] for g in body["unconverted_gaps"]} == {t["title"] for t in FOUR}
    else:
        assert body["unconverted_gaps"] == []
    assert assumption_rows(sync_engine, opp["id"]) == []


def test_a_gap_that_stops_being_open_during_the_call_is_dropped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    respond = by_title(*HAPPY)

    def superseding(request: StructuredRequest[Any]) -> AssumptionsOutput:
        with sync_engine.begin() as conn:  # a newer detection replaced it meanwhile
            conn.execute(
                sa.text(
                    "UPDATE gaps_gaps SET status = 'superseded', row_version = row_version + 1 "
                    "WHERE opportunity_id = :o AND title = 'SSO provider'"
                ),
                {"o": opp["id"]},
            )
        return respond(request)

    gateway.replies = [superseding]

    assert drain(db_url, PROPOSE) == ["succeeded"]

    gaps = gap_rows(sync_engine, opp["id"])
    stored = assumption_rows(sync_engine, opp["id"])
    assert {a["origin_ref"]["id"] for a in stored} == {
        str(gaps[t]["id"]) for t in ("WMS version unknown", "Peak order volume", "Test data owner")
    }
    (event,) = events(sync_engine, opp["id"], "estimates.assumption.proposed")
    assert (event["payload"]["count"], event["payload"]["dropped_count"]) == (3, 1)
    assert event["payload"]["unconverted_count"] == 0
    body = _register(client, headers, opp["id"])
    assert body["unconverted_gaps"] == []
    assert body["counts"]["total"] == 3
