"""Submission blockers and Estimate submission (Story 8.6) against a real, migrated Postgres
as psa_app, with the fake ModelGateway and hidden jobs of `test_intake_extraction.py`:
`get_submission_blockers` (every kind, with hrefs), the list's `blocker_count` equal to the
query, an override leaving the blockers, submit (409 with blockers, 412, 428, not draft, who
may, supersede and the trace), immutability after submission, and accept racing submit.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.estimates.application import assumptions as estimates_assumptions
from app.modules.estimates.application import public as estimates
from app.modules.identity.application.public import Principal, Role
from app.platform.actor import Actor
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.uow import unit_of_work
from tests import test_assessments_red_team as red_team_tests
from tests import test_estimates_assumptions as assumption_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_assessments_findings_decisions import override
from tests.test_assessments_red_team import finding, findings_out
from tests.test_estimates_assumptions import events, proposed
from tests.test_estimates_draft import SIX, lines_out
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DRAFT, PROPOSE, RED_TEAM, FakeGateway, drain
from tests.test_opportunities import PSE, _add, _conflict, _create, _estimate_version, _gap, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_review_profile = red_team_tests._review_profile
_proposal_profile = assumption_tests._proposal_profile

SUBMITTED = "estimates.estimate_version.submitted"
SUPERSEDED = "estimates.estimate_version.superseded"


# --- helpers --------------------------------------------------------------------------------


def assert_blocked(body: dict[str, Any]) -> None:
    """A 409 `estimate_version_blocked` problem: the standard members plus `blockers`."""
    assert set(body["blockers"]) == {"to_submit", "to_baseline"}
    assert_problem(
        {k: v for k, v in body.items() if k != "blockers"}, 409, "estimate_version_blocked"
    )


def blockers(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/{opp_id}/submission-blockers", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def kinds(view: dict[str, Any]) -> list[str]:
    return [b["kind"] for b in view["to_submit"]]


def estimate(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/{opp_id}/estimate", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def submit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    version_id: str,
    row_version: int | None,
) -> Any:
    extra = {} if row_version is None else {"If-Match": f'"{row_version}"'}
    return client.post(
        f"{BASE}/{opp_id}/estimate/versions/{version_id}/submit", headers={**headers, **extra}
    )


def submit_current(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    version = blockers(client, headers, opp_id)["version"]
    return submit(client, headers, opp_id, version["id"], version["row_version"])


def assumptions(client: TestClient, headers: dict[str, str], opp_id: str) -> list[dict[str, Any]]:
    groups = estimate(client, headers, opp_id)["version"]["assumptions"]
    return [*groups["conditions"], *groups["contingencies"]]


def accept(client: TestClient, headers: dict[str, str], opp_id: str, a: dict[str, Any]) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/assumptions/{a['id']}/accept",
        headers={**headers, "If-Match": f'"{a["row_version"]}"'},
    )


def reviewed(
    client: TestClient,
    engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    severity: str = "high",
) -> tuple[dict[str, str], dict[str, Any]]:
    """`proposed` (4 open Gaps, draft v1 of the SIX lines covering R1-R5, 4 unaccepted
    Assumptions) with a current Red Team Review of one Finding of `severity`."""
    headers, opp = proposed(client, engine, db_url, gateway)
    gateway.replies = [findings_out(finding("Peak volume unknown", ["R3"], severity=severity))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    return headers, opp


def ready(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any]]:
    """`reviewed` with every Assumption accepted (so every Gap converted): nothing blocks."""
    headers, opp = reviewed(client, engine, db_url, gateway)
    accepted = client.post(f"{BASE}/{opp['id']}/assumptions/accept-all", headers=headers)
    assert accepted.status_code == 200, accepted.text
    return headers, opp


def add_requirement(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    created = client.post(
        f"{BASE}/{opp_id}/requirements",
        headers=headers,
        json={"text": "The system shall export a nightly stock report.", "classification": "data"},
    )
    assert created.status_code == 201, created.text
    return created.json()  # type: ignore[no-any-return]


def version_rows(engine: Engine, opp_id: str) -> dict[int, dict[str, Any]]:
    found = rows(
        engine, "SELECT * FROM estimates_estimate_versions WHERE opportunity_id = :o", o=opp_id
    )
    return {v["version"]: v for v in found}


def list_row(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    items = client.get(BASE, headers=headers, params={"scope": "mine", "page_size": 200}).json()
    return next(i for i in items["items"] if i["id"] == opp_id)  # type: ignore[no-any-return]


def query_count(db_url: str, opp_ids: list[str]) -> dict[UUID, int]:
    async def scenario() -> dict[UUID, int]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                found = {}
                for opp_id in opp_ids:
                    _, view = await _current(uow, UUID(opp_id))
                    found[UUID(opp_id)] = len(view.to_submit)
                return found
        finally:
            await engine.dispose()

    return run_async(scenario())


async def _current(uow: Any, opportunity_id: UUID) -> Any:
    from app.modules.estimates.application import blockers as blocker_queries

    return await blocker_queries.current_blockers(uow, opportunity_id)


def batched_count(db_url: str, opp_ids: list[str]) -> dict[UUID, int]:
    async def scenario() -> dict[UUID, int]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await estimates.submission_blocker_counts(uow, [UUID(o) for o in opp_ids])
        finally:
            await engine.dispose()

    return run_async(scenario())


# --- the query ------------------------------------------------------------------------------


def test_every_kind_blocks_with_a_link_and_the_list_counts_the_same(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway, severity="critical")
    opp_id = opp["id"]
    for a in assumptions(client, headers, opp_id)[:2]:  # 2 Gaps converted, 2 left open
        assert accept(client, headers, opp_id, a).status_code == 200
    _conflict(sync_engine, opp_id, "escalated")
    requirement = add_requirement(client, headers, opp_id)

    view = blockers(client, headers, opp_id)

    assert kinds(view) == [
        "gap",
        "gap",
        "assumption",
        "assumption",
        "conflict",
        "finding",
        "uncovered_requirement",
    ]
    assert view["to_baseline"] == []
    assert view["can_submit"] is True  # the owner may; the blockers still decide
    assert view["version"]["status"] == "draft"
    uncovered = view["to_submit"][-1]
    assert uncovered["subject_id"] == requirement["id"]
    assert uncovered["title"] == f"R{requirement['number']} not covered"
    tabs = {b["kind"]: b["href"].split("/")[3].split("#")[0] for b in view["to_submit"]}
    assert tabs == {
        "gap": "gaps",
        "assumption": "estimate",
        "conflict": "conflicts",
        "finding": "assessments",
        "uncovered_requirement": "requirements",
    }
    prefixes = {
        "gap": "gap",
        "assumption": "assumption",
        "conflict": "conflict",
        "finding": "finding",
        "uncovered_requirement": "requirement",
    }
    for b in view["to_submit"]:
        assert b["href"].startswith(f"/opportunities/{opp_id}/")
        # The web rows carry these ids (`anchorId`): `#<prefix>-<subject_id>`.
        assert b["href"].split("#", 1)[1] == f"{prefixes[b['kind']]}-{b['subject_id']}"
    assert estimate(client, headers, opp_id)["blockers"]["to_submit"] == view["to_submit"]
    assert list_row(client, headers, opp_id)["blocker_count"] == 7
    assert batched_count(db_url, [opp_id]) == query_count(db_url, [opp_id]) == {UUID(opp_id): 7}

    # An overridden Finding no longer blocks (Story 6.6).
    review = client.get(f"{BASE}/{opp_id}/red-team", headers=headers).json()["review"]
    assert override(client, headers, opp_id, review["findings"][0]).status_code == 200
    after = blockers(client, headers, opp_id)
    assert "finding" not in kinds(after)
    assert len(after["to_submit"]) == 6
    assert list_row(client, headers, opp_id)["blocker_count"] == 6


def test_the_batched_count_equals_the_query_for_a_page(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, _ = _user(client, sync_engine, "Counting Person", PSE)
    plain, superseded_only, drafted, submitted, redrafted = (
        _create(client, headers) for _ in range(5)
    )
    _gap(sync_engine, plain["id"])
    _conflict(sync_engine, plain["id"], "open")
    _conflict(sync_engine, plain["id"], "resolved")
    _estimate_version(sync_engine, superseded_only["id"], 1, status="superseded")
    _estimate_version(
        sync_engine, drafted["id"], 1, lines=(10.0,), contingencies=((1.0, 0), (2.0, None))
    )
    _estimate_version(sync_engine, submitted["id"], 1, status="submitted", lines=(5.0,))
    _gap(sync_engine, submitted["id"])  # past the gate: a submitted version counts none
    # A submitted v1 and a newer draft v2: the draft is current and counts its blockers.
    _estimate_version(sync_engine, redrafted["id"], 1, status="submitted", lines=(5.0,))
    _estimate_version(sync_engine, redrafted["id"], 2, lines=(5.0,), contingencies=((1.0, 0),))
    _gap(sync_engine, redrafted["id"])
    ids = [o["id"] for o in (plain, superseded_only, drafted, submitted, redrafted)]

    counted = batched_count(db_url, ids)

    assert counted == query_count(db_url, ids)
    assert counted == {
        UUID(ids[0]): 2,
        UUID(ids[1]): 0,
        UUID(ids[2]): 2,
        UUID(ids[3]): 0,
        UUID(ids[4]): 2,
    }
    assert [list_row(client, headers, i)["blocker_count"] for i in ids] == [2, 0, 2, 0, 2]
    assert list_row(client, headers, ids[4])["estimate"] == {
        "version": 2,
        "status": "draft",
        "total_hours": 6.0,
    }


def test_nothing_open_is_ready(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = ready(client, sync_engine, db_url, gateway)

    view = blockers(client, headers, opp["id"])
    shown = estimate(client, headers, opp["id"])

    assert view["to_submit"] == []
    assert view["can_submit"] is True
    assert shown["blockers"] == {"to_submit": [], "to_baseline": []}
    assert shown["can_submit"] is True
    assert list_row(client, headers, opp["id"])["blocker_count"] == 0


# --- submit ---------------------------------------------------------------------------------


def test_submit_supersedes_the_earlier_submitted_version_and_traces_both(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = ready(client, sync_engine, db_url, gateway)
    opp_id = opp["id"]
    first = submit_current(client, headers, opp_id)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "submitted"
    assert first.json()["superseded_count"] == 0
    assert first.headers["ETag"] == f'"{first.json()["row_version"]}"'

    # v1 is now the current version: submitted, read-only, not submittable again.
    shown = estimate(client, headers, opp_id)
    assert (shown["version"]["version"], shown["version"]["status"]) == (1, "submitted")
    assert shown["can_submit"] is False
    assert shown["version"]["submitted_at"] is not None
    assert blockers(client, headers, opp_id)["version"]["submitted_at"] is not None
    assert list_row(client, headers, opp_id)["estimate"]["version"] == 1

    # A re-draft makes v2 the draft (carrying v1's accepted Assumptions); submit it.
    draft_tests.requeue(db_url, opp_id)
    gateway.replies = [lines_out(*SIX)]
    assert drain(db_url, DRAFT) == ["succeeded"]
    assert drain(db_url, PROPOSE) == ["succeeded"]  # no open Gap: nothing to propose
    assert estimate(client, headers, opp_id)["version"]["status"] == "draft"
    second = submit_current(client, headers, opp_id)

    assert second.status_code == 200, second.text
    assert (second.json()["version"], second.json()["superseded_count"]) == (2, 1)
    stored = version_rows(sync_engine, opp_id)
    assert (stored[1]["status"], stored[2]["status"]) == ("superseded", "submitted")
    submitted = events(sync_engine, opp_id, SUBMITTED)
    superseded = events(sync_engine, opp_id, SUPERSEDED)
    assert [e["payload"]["version"] for e in submitted] == [1, 2]
    assert submitted[1]["payload"] == {
        "version_id": str(stored[2]["id"]),
        "version": 2,
        "line_count": 6,
        "assumption_count": 4,
        "superseded_count": 1,
    }
    assert submitted[1]["actor_id"] == opp["owner"]["id"]
    assert [e["payload"] for e in superseded] == [
        {
            "version_id": str(stored[1]["id"]),
            "version": 1,
            "superseded_by_version_id": str(stored[2]["id"]),
            "superseded_by_version": 2,
        }
    ]
    assert superseded[0]["subject_id"] == stored[1]["id"]


def test_a_blocker_appearing_after_the_page_loaded_is_409_with_the_blockers(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = ready(client, sync_engine, db_url, gateway)
    loaded = blockers(client, headers, opp["id"])
    assert loaded["to_submit"] == []
    _gap(sync_engine, opp["id"])  # e.g. a Gap reopened on another tab

    response = submit(
        client, headers, opp["id"], loaded["version"]["id"], loaded["version"]["row_version"]
    )

    body = response.json()
    assert_blocked(body)
    assert body["detail"] == "Resolve 1 blocker before you can submit."
    assert [b["kind"] for b in body["blockers"]["to_submit"]] == ["gap"]
    assert body["blockers"]["to_baseline"] == []
    assert version_rows(sync_engine, opp["id"])[1]["status"] == "draft"
    assert events(sync_engine, opp["id"], SUBMITTED) == []


def test_stale_missing_if_match_and_not_draft(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = ready(client, sync_engine, db_url, gateway)
    version = blockers(client, headers, opp["id"])["version"]

    stale = submit(client, headers, opp["id"], version["id"], version["row_version"] + 5)
    missing = submit(client, headers, opp["id"], version["id"], None)
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert_problem(missing.json(), 428, "if_match_required")
    assert version_rows(sync_engine, opp["id"])[1]["status"] == "draft"

    done = submit(client, headers, opp["id"], version["id"], version["row_version"])
    assert done.status_code == 200
    again = submit(client, headers, opp["id"], version["id"], version["row_version"] + 1)
    assert_problem(again.json(), 409, "estimate_version_not_draft")
    assert len(events(sync_engine, opp["id"], SUBMITTED)) == 1
    unknown = submit(client, headers, opp["id"], str(uuid4()), 1)
    assert_problem(unknown.json(), 404, "not_found")


def test_who_may_submit(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = ready(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep_id).status_code == 200
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    seen = blockers(client, rep, opp["id"])
    assert (seen["to_submit"], seen["can_submit"]) == ([], False)
    assert estimate(client, rep, opp["id"])["can_submit"] is False
    version = seen["version"]
    assert_problem(
        submit(client, rep, opp["id"], version["id"], version["row_version"]).json(),
        403,
        "forbidden",
    )
    hidden = client.get(f"{BASE}/{opp['id']}/submission-blockers", headers=outsider)
    assert_problem(hidden.json(), 404, "not_found")
    assert_problem(
        submit(client, outsider, opp["id"], version["id"], version["row_version"]).json(),
        404,
        "not_found",
    )
    assert version_rows(sync_engine, opp["id"])[1]["status"] == "draft"


def test_a_submitted_version_is_immutable(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    found = assumptions(client, headers, opp["id"])
    for a in found:
        assert accept(client, headers, opp["id"], a).status_code == 200
    assert submit_current(client, headers, opp["id"]).status_code == 200
    line = estimate(client, headers, opp["id"])["version"]["sections"][0]["lines"][0]
    line_sql = "SELECT * FROM estimates_estimate_lines WHERE id = :i"
    before = rows(sync_engine, line_sql, i=line["id"])

    edited = client.patch(
        f"{BASE}/{opp['id']}/estimate-lines/{line['id']}",
        headers={**headers, "If-Match": f'"{line["row_version"]}"'},
        json={"effort_hours": 99, "reason": "Too late"},
    )
    accepted = accept(client, headers, opp["id"], found[0])
    accepted_all = client.post(f"{BASE}/{opp['id']}/assumptions/accept-all", headers=headers)

    assert_problem(edited.json(), 409, "estimate_version_not_draft")
    assert edited.json()["detail"].startswith("This Estimate Version was submitted")
    assert_problem(accepted.json(), 409, "estimate_version_not_draft")
    assert_problem(accepted_all.json(), 409, "estimate_version_not_draft")
    assert rows(sync_engine, line_sql, i=line["id"]) == before


def test_a_submitted_version_has_no_blockers_and_the_list_says_submitted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = ready(client, sync_engine, db_url, gateway)
    assert submit_current(client, headers, opp["id"]).status_code == 200

    add_requirement(client, headers, opp["id"])  # uncovered, but after the gate was passed
    view = blockers(client, headers, opp["id"])
    row = list_row(client, headers, opp["id"])

    assert view["version"]["status"] == "submitted"
    assert view["to_submit"] == []
    assert view["can_submit"] is False
    assert row["blocker_count"] == 0
    assert row["estimate"]["status"] == "submitted"
    assert batched_count(db_url, [opp["id"]]) == {UUID(opp["id"]): 0}


# --- serialisation --------------------------------------------------------------------------


def test_accept_and_submit_serialise_on_the_lock(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    """Accept holds the lock with the last Assumption accepted but not committed; submit waits
    for it and then sees no blocker, so the outcome matches the blockers at its commit."""
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    opp_id = UUID(opp["id"])
    *others, last = assumptions(client, headers, opp["id"])
    for a in others:
        assert accept(client, headers, opp["id"], a).status_code == 200
    version = blockers(client, headers, opp["id"])["version"]
    owner = Principal(Actor("user", opp["owner"]["id"]), frozenset({Role.PRESALES_ENGINEER}))

    async def scenario() -> tuple[bool, list[Any]]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        accepted = asyncio.Event()
        release = asyncio.Event()

        async def first() -> Any:
            async with unit_of_work(engine) as uow:
                done = await estimates_assumptions.accept_assumption(
                    uow, owner, opp_id, UUID(last["id"]), f'"{last["row_version"]}"'
                )
                accepted.set()
                await release.wait()  # hold the locks, uncommitted
                return done

        async def second() -> Any:
            await accepted.wait()
            async with unit_of_work(engine) as uow:
                return await estimates.submit_version(
                    uow, owner, opp_id, UUID(version["id"]), f'"{version["row_version"]}"'
                )

        try:
            t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
            await accepted.wait()
            await asyncio.sleep(0.5)
            second_blocked = not t2.done()
            release.set()
            return second_blocked, await asyncio.gather(t1, t2, return_exceptions=True)
        finally:
            await engine.dispose()

    second_blocked, (a, b) = run_async(scenario())

    assert second_blocked
    assert not isinstance(a, BaseException), a
    assert not isinstance(b, BaseException), b
    assert b.status == "submitted"
    assert version_rows(sync_engine, opp["id"])[1]["status"] == "submitted"


def test_an_unaccepted_assumption_blocks_and_a_late_accept_is_not_draft(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    """Submitting with an Assumption still unaccepted is refused; once the version is
    submitted, a late accept is refused too (nothing slips in after the check)."""
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    *others, last = assumptions(client, headers, opp["id"])
    for a in others:
        assert accept(client, headers, opp["id"], a).status_code == 200
    blocked = submit_current(client, headers, opp["id"])
    assert_blocked(blocked.json())
    assert [b["kind"] for b in blocked.json()["blockers"]["to_submit"]] == ["gap", "assumption"]
    assert accept(client, headers, opp["id"], last).status_code == 200
    assert submit_current(client, headers, opp["id"]).status_code == 200
    late = accept(client, headers, opp["id"], last)
    assert_problem(late.json(), 409, "estimate_version_not_draft")
