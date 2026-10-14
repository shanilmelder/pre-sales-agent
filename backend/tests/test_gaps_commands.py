"""Changing impact, dismissing and reopening Gaps, and approving selected questions (Story 4.4,
demo slice) against a real, migrated Postgres as psa_app: `PATCH …/gaps/{gid}/impact`,
`POST …/gaps/{gid}/dismiss`, `POST …/gaps/{gid}/reopen`, `POST
…/clarification-questions/approve-selected`, the list order and history, the sales
representative's view, `irrelevance_share` and the re-detection rule. Reuses the fake
ModelGateway and hidden jobs of `test_intake_extraction.py`."""

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.gaps.application import public as gaps_public
from app.platform.actor import Actor
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.uow import unit_of_work
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_gaps_detection import events, gap, gaps_out, requeue, rows
from tests.test_gaps_questions import _approve, _gaps, _if_match, _shown, detected
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, FakeGateway, drain
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile

IMPACT_CHANGED = "gaps.gap.impact_changed"
DISMISSED = "gaps.gap.dismissed"
REOPENED = "gaps.gap.reopened"
APPROVED = "gaps.clarification_question.approved"
SECRET_REASON = "Customer confirmed the SAP interface is out of scope"


def _by_title(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    return {g["title"]: g for g in _gaps(client, headers, opp_id)["items"]}


def _url(opp_id: str, gap: dict[str, Any], action: str) -> str:
    return f"{BASE}/{opp_id}/gaps/{gap['id']}/{action}"


def _impact(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    gap: dict[str, Any],
    body: dict[str, Any],
    version: int | None = None,
) -> Any:
    v = gap["row_version"] if version is None else version
    return client.patch(_url(opp_id, gap, "impact"), headers={**headers, **_if_match(v)}, json=body)


def _dismiss(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    gap: dict[str, Any],
    body: dict[str, Any],
    version: int | None = None,
) -> Any:
    v = gap["row_version"] if version is None else version
    return client.post(_url(opp_id, gap, "dismiss"), headers={**headers, **_if_match(v)}, json=body)


def _reopen(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    gap: dict[str, Any],
    body: dict[str, Any],
    version: int | None = None,
) -> Any:
    v = gap["row_version"] if version is None else version
    return client.post(_url(opp_id, gap, "reopen"), headers={**headers, **_if_match(v)}, json=body)


def _approve_selected(client: TestClient, headers: dict[str, str], opp_id: str, body: Any) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/clarification-questions/approve-selected", headers=headers, json=body
    )


def _gap_row(engine: Engine, gap_id: str) -> dict[str, Any]:
    (row,) = rows(engine, "SELECT * FROM gaps_gaps WHERE id = :g", g=gap_id)
    return row


def _history_rows(engine: Engine, gap_id: str) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM gaps_gap_history WHERE gap_id = :g ORDER BY at", g=gap_id)


def _share(db_url: str, opp_id: str | None) -> dict[str, int]:
    async def scenario() -> dict[str, int]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                share = await gaps_public.irrelevance_share(
                    uow, None if opp_id is None else UUID(opp_id)
                )
                return share.model_dump()
        finally:
            await engine.dispose()

    return run_async(scenario())


# --- impact ---------------------------------------------------------------------------------


def test_lowering_an_impact_re_ranks_the_list_with_history_and_an_event(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=3)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    assert sap["impact"] == "high"
    assert [h["kind"] for h in sap["history"]] == ["raised"]
    assert sap["history"][0]["actor"] == "agent"
    assert sap["dismissal"] is None

    with caplog.at_level(logging.DEBUG):
        resp = _impact(
            client, headers, opp["id"], sap, {"impact": "low", "reason": f" {SECRET_REASON} "}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["ETag"] == '"2"'
    assert (body["impact"], body["row_version"]) == ("low", 2)
    assert body["last_changed_by"]["name"] == "Owner Person"
    raised, changed = body["history"]
    assert raised["kind"] == "raised"
    assert changed["kind"] == "impact_changed"
    assert (changed["old_impact"], changed["new_impact"]) == ("high", "low")
    assert changed["reason"] == SECRET_REASON
    assert changed["actor"]["name"] == "Owner Person"
    titles = [g["title"] for g in _gaps(client, headers, opp["id"])["items"]]
    assert titles == ["Uptime window", "Peak growth", "SAP interface type"]
    assert _gap_row(sync_engine, sap["id"])["touched_by_human"] is True
    (event,) = events(sync_engine, opp["id"], IMPACT_CHANGED)
    assert event["payload"] == {"old_impact": "high", "new_impact": "low", "row_version": 2}
    assert (event["subject_type"], str(event["subject_id"])) == ("gaps.gap", sap["id"])
    # Privacy: no reason text in logs or trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    assert "out of scope" not in logged
    assert "out of scope" not in str(events(sync_engine, opp["id"]))


def test_the_same_impact_writes_nothing_but_a_stale_one_is_still_412(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]

    same = _impact(client, headers, opp["id"], sap, {"impact": "high", "reason": "Still high"})

    assert same.status_code == 200, same.text
    assert same.json() == sap
    assert _history_rows(sync_engine, sap["id"]) == []
    assert events(sync_engine, opp["id"], IMPACT_CHANGED) == []
    stale = _impact(client, headers, opp["id"], sap, {"impact": "high", "reason": "x"}, 9)
    assert_problem(stale.json(), 412, "row_version_mismatch")


@pytest.mark.parametrize(
    "body",
    [
        {"impact": "low", "reason": ""},
        {"impact": "low", "reason": "   "},
        {"impact": "low", "reason": "x" * 501},
        {"impact": "low"},
        {"impact": "huge", "reason": "Why"},
        {"impact": "low", "reason": "Why", "status": "dismissed"},
    ],
)
def test_an_invalid_impact_change_is_422_and_changes_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    body: dict[str, Any],
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    before = _gap_row(sync_engine, sap["id"])

    resp = _impact(client, headers, opp["id"], sap, body)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert _gap_row(sync_engine, sap["id"]) == before


def test_a_500_character_reason_is_accepted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]

    resp = _impact(client, headers, opp["id"], sap, {"impact": "medium", "reason": "x" * 500})

    assert resp.status_code == 200, resp.text


# --- dismiss and reopen ---------------------------------------------------------------------


def test_dismissing_as_not_relevant_greys_it_last_and_counts_it(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=3)
    assert _share(db_url, opp["id"]) == {"raised": 3, "dismissed_not_relevant": 0}
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]

    resp = _dismiss(client, headers, opp["id"], sap, {"reason_kind": "not_relevant"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["row_version"]) == ("dismissed", 2)
    assert body["dismissal"]["reason_kind"] == "not_relevant"
    assert body["dismissal"]["note"] is None
    assert body["dismissal"]["by"]["name"] == "Owner Person"
    assert body["history"][-1]["kind"] == "dismissed"
    assert body["history"][-1]["reason_kind"] == "not_relevant"
    listed = _gaps(client, headers, opp["id"])["items"]
    assert [(g["title"], g["status"]) for g in listed] == [
        ("Uptime window", "open"),
        ("Peak growth", "open"),
        ("SAP interface type", "dismissed"),
    ]
    (event,) = events(sync_engine, opp["id"], DISMISSED)
    assert event["payload"] == {"reason_kind": "not_relevant", "row_version": 2}
    assert _share(db_url, opp["id"]) == {"raised": 3, "dismissed_not_relevant": 1}
    everywhere = _share(db_url, None)
    assert everywhere["dismissed_not_relevant"] >= 1
    assert everywhere["raised"] >= 3
    # A dismissed Gap's question is no longer in Approve all's set.
    assert sap["question"]["id"] not in {q["id"] for q in _shown(client, headers, opp["id"])}


def test_dismissing_as_other_needs_a_note(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    before = _gap_row(sync_engine, sap["id"])

    for body in (
        {"reason_kind": "other"},
        {"reason_kind": "other", "note": "  "},
        {"reason_kind": "not_relevant", "note": "x" * 501},
        {"reason_kind": "duplicate"},
    ):
        resp = _dismiss(client, headers, opp["id"], sap, body)
        assert resp.status_code == 422, resp.text
        assert_problem(resp.json(), 422, "validation_error")
    assert _gap_row(sync_engine, sap["id"]) == before
    assert events(sync_engine, opp["id"], DISMISSED) == []

    resp = _dismiss(
        client, headers, opp["id"], sap, {"reason_kind": "other", "note": SECRET_REASON}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["dismissal"]["note"] == SECRET_REASON
    row = _gap_row(sync_engine, sap["id"])
    assert (row["dismiss_reason_kind"], row["dismiss_note"]) == ("other", SECRET_REASON)
    assert "out of scope" not in str(events(sync_engine, opp["id"]))
    assert _share(db_url, opp["id"]) == {"raised": 1, "dismissed_not_relevant": 0}


def test_reopening_ranks_it_again_and_keeps_the_history(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    dismissed = _dismiss(
        client, headers, opp["id"], sap, {"reason_kind": "other", "note": "Duplicate"}
    ).json()

    resp = _reopen(client, headers, opp["id"], dismissed, {"reason": "Customer brought it back"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["row_version"], body["dismissal"]) == ("open", 3, None)
    assert [h["kind"] for h in body["history"]] == ["raised", "dismissed", "reopened"]
    assert body["history"][1]["reason"] == "Duplicate"
    assert body["history"][2]["reason"] == "Customer brought it back"
    row = _gap_row(sync_engine, sap["id"])
    assert (row["dismiss_reason_kind"], row["dismiss_note"], row["dismissed_by"]) == (
        None,
        None,
        None,
    )
    assert row["dismissed_at"] is None
    assert row["touched_by_human"] is True
    titles = [g["title"] for g in _gaps(client, headers, opp["id"])["items"]]
    assert titles == ["SAP interface type", "Uptime window"]
    (event,) = events(sync_engine, opp["id"], REOPENED)
    assert event["payload"] == {"row_version": 3}
    assert "brought it back" not in str(events(sync_engine, opp["id"]))


def test_the_wrong_state_is_409_and_changes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    by_title = _by_title(client, headers, opp["id"])
    sap, uptime = by_title["SAP interface type"], by_title["Uptime window"]
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE gaps_gaps SET status = 'converted', converted_to = 'condition' "
                "WHERE id = :g"
            ),
            {"g": sap["id"]},
        )
    before = (_gap_row(sync_engine, sap["id"]), _gap_row(sync_engine, uptime["id"]))

    converted_dismiss = _dismiss(client, headers, opp["id"], sap, {"reason_kind": "not_relevant"})
    converted_impact = _impact(client, headers, opp["id"], sap, {"impact": "low", "reason": "x"})
    open_reopen = _reopen(client, headers, opp["id"], uptime, {"reason": "Why not"})

    for resp in (converted_dismiss, converted_impact):
        assert resp.status_code == 409, resp.text
        assert_problem(resp.json(), 409, "gap_not_open")
    assert_problem(open_reopen.json(), 409, "gap_not_dismissed")
    assert (_gap_row(sync_engine, sap["id"]), _gap_row(sync_engine, uptime["id"])) == before
    assert events(sync_engine, opp["id"], "gaps.gap.d") == []
    assert events(sync_engine, opp["id"], "gaps.gap.re") == []
    # A dismissed Gap's impact doesn't change either, and it can't be dismissed twice.
    dismissed = _dismiss(client, headers, opp["id"], uptime, {"reason_kind": "not_relevant"}).json()
    for resp in (
        _impact(client, headers, opp["id"], dismissed, {"impact": "high", "reason": "x"}),
        _dismiss(client, headers, opp["id"], dismissed, {"reason_kind": "not_relevant"}),
    ):
        assert_problem(resp.json(), 409, "gap_not_open")


def test_a_stale_or_missing_if_match_changes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    changed = _impact(client, headers, opp["id"], sap, {"impact": "medium", "reason": "Why"})
    assert changed.status_code == 200
    before = _gap_row(sync_engine, sap["id"])

    stale = (
        _impact(client, headers, opp["id"], sap, {"impact": "low", "reason": "x"}),
        _dismiss(client, headers, opp["id"], sap, {"reason_kind": "not_relevant"}),
    )
    missing = (
        client.patch(
            _url(opp["id"], sap, "impact"), headers=headers, json={"impact": "low", "reason": "x"}
        ),
        client.post(
            _url(opp["id"], sap, "dismiss"), headers=headers, json={"reason_kind": "not_relevant"}
        ),
        client.post(_url(opp["id"], sap, "reopen"), headers=headers, json={"reason": "x"}),
    )

    for resp in stale:
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    for resp in missing:
        assert resp.status_code == 428, resp.text
        assert_problem(resp.json(), 428, "if_match_required")
    assert _gap_row(sync_engine, sap["id"]) == before
    assert len(events(sync_engine, opp["id"], IMPACT_CHANGED)) == 1
    assert events(sync_engine, opp["id"], DISMISSED) == []
    # The 412 view can name who changed it.
    current = _by_title(client, headers, opp["id"])["SAP interface type"]
    assert current["last_changed_by"]["name"] == "Owner Person"


def test_unknown_or_foreign_gaps_are_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    other_headers, other = detection_tests.extracted(client, sync_engine, db_url, gateway)

    unknown = _dismiss(
        client, headers, opp["id"], {**sap, "id": str(uuid4())}, {"reason_kind": "not_relevant"}
    )
    foreign = _dismiss(client, other_headers, other["id"], sap, {"reason_kind": "not_relevant"})

    for resp in (unknown, foreign):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
    bad = client.post(
        f"{BASE}/{opp['id']}/gaps/nope/reopen",
        headers={**headers, **_if_match(1)},
        json={"reason": "x"},
    )
    assert bad.status_code == 422


# --- who ------------------------------------------------------------------------------------


def test_sales_reps_may_not_change_gaps_and_see_history_without_reasons(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    added = _add(client, headers, opp, rep_id)
    assert added.status_code == 200, added.text
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    by_title = _by_title(client, headers, opp["id"])
    sap, uptime = by_title["SAP interface type"], by_title["Uptime window"]

    for resp in (
        _impact(client, rep, opp["id"], sap, {"impact": "low", "reason": "x"}),
        _dismiss(client, rep, opp["id"], sap, {"reason_kind": "not_relevant"}),
        _reopen(client, rep, opp["id"], sap, {"reason": "x"}),
        _approve_selected(
            client, rep, opp["id"], [{"id": sap["question"]["id"], "row_version": 1}]
        ),
    ):
        assert resp.status_code == 403, resp.text
        assert_problem(resp.json(), 403, "forbidden")
    outside = _dismiss(client, outsider, opp["id"], sap, {"reason_kind": "not_relevant"})
    assert outside.status_code == 404
    assert events(sync_engine, opp["id"], "gaps.gap.") == [
        e for e in events(sync_engine, opp["id"], "gaps.gap.") if e["event_type"].endswith("raised")
    ]

    _impact(client, headers, opp["id"], uptime, {"impact": "low", "reason": SECRET_REASON})
    _dismiss(client, headers, opp["id"], sap, {"reason_kind": "other", "note": SECRET_REASON})

    seen = _gaps(client, rep, opp["id"])
    assert seen["can_edit_gaps"] is False
    assert _gaps(client, headers, opp["id"])["can_edit_gaps"] is True
    rep_view = {g["title"]: g for g in seen["items"]}
    assert rep_view["SAP interface type"]["dismissal"]["reason_kind"] == "other"
    assert rep_view["SAP interface type"]["dismissal"]["note"] is None
    assert rep_view["SAP interface type"]["dismissal"]["by"]["name"] == "Owner Person"
    assert [h["kind"] for h in rep_view["Uptime window"]["history"]] == [
        "raised",
        "impact_changed",
    ]
    assert {h["reason"] for g in seen["items"] for h in g["history"]} == {None}
    assert "out of scope" not in str(seen)


# --- approve selected -----------------------------------------------------------------------


def test_approve_selected_approves_exactly_the_listed_questions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=4)
    shown = _shown(client, headers, opp["id"])

    resp = _approve_selected(client, headers, opp["id"], shown[:2])

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 2}
    statuses = {
        g["question"]["id"]: g["question"]["status"]
        for g in _gaps(client, headers, opp["id"])["items"]
    }
    assert [statuses[q["id"]] for q in shown] == ["approved", "approved", "drafted", "drafted"]
    assert len(events(sync_engine, opp["id"], APPROVED)) == 2


def test_approve_selected_is_all_or_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=4)
    shown = _shown(client, headers, opp["id"])
    by_id = {g["question"]["id"]: g for g in _gaps(client, headers, opp["id"])["items"]}
    assert (
        _approve(client, headers, opp["id"], by_id[shown[0]["id"]]["question"]).status_code == 200
    )
    dismissed = _dismiss(
        client, headers, opp["id"], by_id[shown[1]["id"]], {"reason_kind": "not_relevant"}
    )
    assert dismissed.status_code == 200

    not_drafted = _approve_selected(client, headers, opp["id"], [shown[0], shown[2]])
    not_open = _approve_selected(client, headers, opp["id"], [shown[1], shown[2]])
    stale = _approve_selected(
        client, headers, opp["id"], [{**shown[2], "row_version": 5}, shown[3]]
    )
    unknown = _approve_selected(
        client, headers, opp["id"], [{"id": str(uuid4()), "row_version": 1}, shown[3]]
    )
    twice = _approve_selected(
        client, headers, opp["id"], [shown[2], {**shown[2], "row_version": 2}]
    )

    for resp in (not_drafted, not_open, stale, unknown, twice):
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    assert len(events(sync_engine, opp["id"], APPROVED)) == 1  # only the single approve
    for body in ([], [{"id": "nope", "row_version": 1}], [shown[2]] * 201):
        assert _approve_selected(client, headers, opp["id"], body).status_code == 422


# --- history of a conversion ----------------------------------------------------------------


def test_a_conversion_is_in_the_history(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    (owner_row,) = rows(
        sync_engine, "SELECT owner_id FROM opportunities_opportunities WHERE id = :o", o=opp["id"]
    )

    async def convert() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await gaps_public.mark_converted(
                    uow,
                    UUID(sap["id"]),
                    actor=Actor("user", str(owner_row["owner_id"])),
                    assumption_kind="condition",
                )
        finally:
            await engine.dispose()

    run_async(convert())

    converted = _by_title(client, headers, opp["id"])["SAP interface type"]
    assert converted["status"] == "converted"
    assert [h["kind"] for h in converted["history"]] == ["raised", "converted"]
    assert converted["history"][1]["actor"]["name"] == "Owner Person"


# --- re-detection ---------------------------------------------------------------------------


def test_a_re_detection_keeps_human_decisions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=3)
    by_title = _by_title(client, headers, opp["id"])
    dismissed = _dismiss(
        client, headers, opp["id"], by_title["SAP interface type"], {"reason_kind": "not_relevant"}
    ).json()
    lowered = _impact(
        client, headers, opp["id"], by_title["Uptime window"], {"impact": "low", "reason": "Why"}
    ).json()
    requeue(db_url, opp["id"])
    gateway.replies = [
        gaps_out(
            gap("  sap   INTERFACE type ", ["R1"], topic="SAP"),  # re-raises the dismissed one
            gap("Price indexation", ["R5"], category="commercial", impact="low"),
            gap("Interface owner", ["R1"], category="scope_and_ownership"),
        )
    ]

    assert drain(db_url, DETECT) == ["succeeded"]

    listed = _gaps(client, headers, opp["id"])["items"]
    assert [(g["title"], g["status"]) for g in listed] == [
        ("Interface owner", "open"),
        ("Uptime window", "open"),
        ("Price indexation", "open"),
        ("SAP interface type", "dismissed"),
    ]
    after = {g["title"]: g for g in listed}
    assert after["SAP interface type"] == dismissed
    assert after["Uptime window"] == lowered
    superseded = rows(
        sync_engine,
        "SELECT title FROM gaps_gaps WHERE opportunity_id = :o AND status = 'superseded'",
        o=opp["id"],
    )
    assert [r["title"] for r in superseded] == ["Peak growth"]
    completed = [
        e["payload"]
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "gaps.detection.completed"
    ]
    assert completed[-1] == {
        "gap_count": 2,
        "dropped_count": 1,
        "requirement_count": 5,
        "superseded_count": 1,
        "kept_count": 1,
    }
    # Superseded Gaps leave the FR-11 "raised" count; the dismissed one stays in it.
    assert _share(db_url, opp["id"]) == {"raised": 4, "dismissed_not_relevant": 1}


def test_a_reopened_gap_is_kept_by_a_re_detection(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=1)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    dismissed = _dismiss(client, headers, opp["id"], sap, {"reason_kind": "not_relevant"}).json()
    reopened = _reopen(client, headers, opp["id"], dismissed, {"reason": "Back"}).json()
    requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("Price indexation", ["R5"], category="commercial"))]

    assert drain(db_url, DETECT) == ["succeeded"]

    after = _by_title(client, headers, opp["id"])
    assert after["SAP interface type"] == reopened
    assert set(after) == {"SAP interface type", "Price indexation"}


# --- the migration --------------------------------------------------------------------------


def test_the_downgrade_reopens_dismissed_gaps_and_drops_the_history(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    sap = _by_title(client, headers, opp["id"])["SAP interface type"]
    dismissed = _dismiss(
        client, headers, opp["id"], sap, {"reason_kind": "other", "note": "Duplicate"}
    )
    assert dismissed.status_code == 200, dismissed.text

    _alembic("downgrade", "0028_workflows")
    try:
        (row,) = rows(sync_engine, "SELECT status FROM gaps_gaps WHERE id = :g", g=sap["id"])
        assert row["status"] == "open"
        (history,) = rows(sync_engine, "SELECT to_regclass('gaps_gap_history') AS t")
        assert history["t"] is None
    finally:
        _alembic("upgrade", "head")

    reopened = _gap_row(sync_engine, sap["id"])
    assert (reopened["status"], reopened["dismiss_reason_kind"]) == ("open", None)
