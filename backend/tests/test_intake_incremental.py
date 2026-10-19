"""Incremental intake with pending changes (Story 2.7) against a real, migrated Postgres as
psa_app, with the fake ModelGateway of `test_intake_extraction.py`: a new Source adds and
refines Requirements in place, a rerun with nothing new writes nothing, changes to
human-locked Requirements become pending changes, and `POST …/change/accept` and
`…/change/reject`."""

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_intake_extraction as extraction_tests
from tests.test_health import assert_problem
from tests.test_intake_extraction import (
    BASE,
    DETECT,
    EXTRACT,
    PARSE,
    FakeGateway,
    _requeue,
    drain,
    out,
    parsed,
    passages,
    requirements,
    upload,
)
from tests.test_intake_requirement_edits import _confirm, _events, _history, _list, _patch, _row
from tests.test_opportunities import PSE, _add, _if_match, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

NOTE = "We must connect to SAP. The site runs 24/7. "
MAIL = "Update: the SAP system is S/4HANA. Orders ship the same day. The site is in Ghent. "
SAP = ("Connect to SAP.", "integration", [("S1", "We must connect to SAP")])
UPTIME = ("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")])
SAP_S4 = (
    "Connect to SAP S/4HANA.",
    "integration",
    [("S1", "We must connect to SAP"), ("S2", "the SAP system is S/4HANA")],
)
SHIPPING = ("Ship orders the same day.", "functional", [("S2", "Orders ship the same day")])


# --- helpers --------------------------------------------------------------------------------


def _first_run(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    """An Opportunity with one Source and two extracted Requirements: SAP (R1), uptime (R2)."""
    headers, opp, _ = parsed(client, engine, db_url, ("call.txt", f"{NOTE}{uuid4()}"))
    gateway.replies = [out(SAP, UPTIME)]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    return headers, opp, _list(client, headers, opp["id"])


def _new_source(
    client: TestClient,
    headers: dict[str, str],
    opp: dict[str, Any],
    db_url: str,
    gateway: FakeGateway,
    *items: tuple[str, str, list[tuple[str, str]]],
) -> None:
    """Add the email Source (S2); its parse queues the extraction that replies `items`."""
    upload(client, headers, opp["id"], "mail.txt", f"{MAIL}{uuid4()}")
    assert drain(db_url, PARSE) == ["succeeded"]
    gateway.replies = [out(*items)]
    assert drain(db_url, EXTRACT) == ["succeeded"]


def _rerun(db_url: str, opp: dict[str, Any], gateway: FakeGateway, *items: Any) -> None:
    _requeue(db_url, opp["id"])
    gateway.replies = [out(*items)]
    assert drain(db_url, EXTRACT) == ["succeeded"]


def _changes(engine: Engine, requirement_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM intake_requirement_changes WHERE requirement_id = :r "
                    "ORDER BY created_at, id"
                ),
                {"r": requirement_id},
            ).mappings()
        ]


def _accept(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.post(
        f"{BASE}/{opp_id}/requirements/{item['id']}/change/accept", headers={**headers, **extra}
    )


def _reject(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    reason: str,
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.post(
        f"{BASE}/{opp_id}/requirements/{item['id']}/change/reject",
        headers={**headers, **extra},
        json={"reason": reason},
    )


def _locked_with_change(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """R1 (SAP) edited by a person, then a new Source that refines it: its pending change."""
    headers, opp, (sap, _) = _first_run(client, engine, db_url, gateway)
    edited = _patch(client, headers, opp["id"], sap, {"text": "SAP link."}, sap["row_version"])
    assert edited.status_code == 200, edited.text
    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME)
    after = {i["id"]: i for i in _list(client, headers, opp["id"])}
    return headers, opp, after[sap["id"]]


# --- new information ------------------------------------------------------------------------


def test_a_new_source_adds_and_refines_unlocked_requirements_in_place(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _first_run(client, sync_engine, db_url, gateway)
    uptime_row = _row(sync_engine, uptime["id"])

    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME, SHIPPING)

    items = _list(client, headers, opp["id"])
    assert [i["text"] for i in items] == [
        "Connect to SAP S/4HANA.",
        "Runs 24/7.",
        "Ship orders the same day.",
    ]
    refined = items[0]
    assert refined["id"] == sap["id"]
    assert (refined["version"], refined["row_version"], refined["origin"]) == (2, 2, "extracted")
    assert refined["locked_by_human"] is False and refined["pending_change"] is None
    assert [e["label"].split(" · ")[0] for e in refined["evidence"]] == ["S1", "S2"]
    history = _history(sync_engine, sap["id"])
    assert [(h["version"], h["created_by"]) for h in history] == [
        (1, "intake_agent@0.1.0"),
        (2, "intake_agent@0.1.0"),
    ]
    (edited,) = _events(sync_engine, sap["id"])
    assert (edited["event_type"], edited["actor_type"], edited["actor_id"]) == (
        "intake.requirement.edited",
        "agent",
        "intake_agent@0.1.0",
    )
    assert edited["payload"] == {"fields": ["text"], "version": 2}
    assert edited["subject_version"] == 2
    # The other one is untouched; nothing is superseded.
    assert _row(sync_engine, uptime["id"]) == uptime_row
    assert _events(sync_engine, uptime["id"]) == []
    assert requirements(sync_engine, opp["id"], "superseded") == []
    # Gap detection is still queued after the accepted extraction.
    with sync_engine.connect() as conn:
        queued = conn.execute(
            sa.text(
                "SELECT count(*) FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o "
                "AND status = 'queued'"
            ),
            {"t": DETECT, "o": opp["id"]},
        ).scalar_one()
    assert queued == 1


def test_a_rerun_with_nothing_new_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, items = _first_run(client, sync_engine, db_url, gateway)
    before = [_row(sync_engine, i["id"]) for i in items]

    reworded = (
        ("Integrate with SAP.", "integration", [("S1", "connect to SAP")]),
        ("Available around the clock.", "non_functional", [("S1", "runs 24/7")]),
    )
    _rerun(db_url, opp, gateway, *reworded)

    assert [_row(sync_engine, i["id"]) for i in items] == before
    assert _list(client, headers, opp["id"]) == items
    for item in items:
        assert len(_history(sync_engine, item["id"])) == 1
        assert _events(sync_engine, item["id"]) == []
        assert _changes(sync_engine, item["id"]) == []


# --- pending changes ------------------------------------------------------------------------


def test_a_change_to_a_locked_requirement_is_proposed_not_applied(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _first_run(client, sync_engine, db_url, gateway)
    confirmed = _confirm(client, headers, opp["id"], sap, sap["row_version"]).json()

    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME)

    after = {i["id"]: i for i in _list(client, headers, opp["id"])}
    item = after[sap["id"]]
    assert (item["text"], item["version"]) == ("Connect to SAP.", 1)
    assert item["evidence"] == confirmed["evidence"]
    assert item["row_version"] == confirmed["row_version"] + 1
    pending = item["pending_change"]
    assert pending is not None
    assert (pending["text"], pending["classification"]) == (
        "Connect to SAP S/4HANA.",
        "integration",
    )
    (chip,) = pending["evidence"]
    assert chip["label"] == "S2 · mail.txt"
    (change,) = _changes(sync_engine, sap["id"])
    assert (change["status"], change["base_version"], str(change["id"])) == (
        "open",
        1,
        pending["id"],
    )
    assert [str(p) for p in change["passage_ids"]] == [chip["passage_id"]]
    assert change["extraction_id"] is not None
    proposed = _events(sync_engine, sap["id"])[-1]
    assert (proposed["event_type"], proposed["actor_id"]) == (
        "intake.requirement_change.proposed",
        "intake_agent@0.1.0",
    )
    assert proposed["payload"] == {
        "change_id": pending["id"],
        "base_version": 1,
        "superseded_change_id": None,
    }
    assert "S/4HANA" not in str(proposed)
    assert after[uptime["id"]] == uptime


def test_the_same_proposal_again_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)

    _rerun(db_url, opp, gateway, SAP_S4, UPTIME)

    assert len(_changes(sync_engine, item["id"])) == 1
    again = {i["id"]: i for i in _list(client, headers, opp["id"])}[item["id"]]
    assert again == item


def test_a_newer_proposal_supersedes_the_open_change(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)
    newer = (
        "Connect to SAP S/4HANA in Ghent.",
        "integration",
        [
            ("S1", "We must connect to SAP"),
            ("S2", "the SAP system is S/4HANA"),
            ("S2", "The site is in Ghent"),
        ],
    )

    _rerun(db_url, opp, gateway, newer, UPTIME)

    old, current = _changes(sync_engine, item["id"])
    assert (old["status"], current["status"]) == ("superseded", "open")
    after = {i["id"]: i for i in _list(client, headers, opp["id"])}[item["id"]]
    assert after["pending_change"]["id"] == str(current["id"])
    assert after["pending_change"]["text"] == "Connect to SAP S/4HANA in Ghent."
    assert len(after["pending_change"]["evidence"]) == 2
    assert after["row_version"] == item["row_version"] + 1
    proposed = _events(sync_engine, item["id"])[-1]
    assert proposed["payload"]["superseded_change_id"] == str(old["id"])


def test_accept_applies_the_change_as_the_next_version(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)
    others = [i for i in _list(client, headers, opp["id"]) if i["id"] != item["id"]]

    response = _accept(client, headers, opp["id"], item, item["row_version"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert response.headers["ETag"] == f'"{body["row_version"]}"'
    assert (body["text"], body["classification"], body["version"]) == (
        "Connect to SAP S/4HANA.",
        "integration",
        3,
    )
    assert (body["origin"], body["locked_by_human"], body["pending_change"]) == (
        "human",
        True,
        None,
    )
    assert [e["label"].split(" · ")[0] for e in body["evidence"]] == ["S1", "S2"]
    assert body["last_changed_by"]["name"] == "Owner Person"
    (change,) = _changes(sync_engine, item["id"])
    assert change["status"] == "accepted"
    assert change["decided_by"] is not None and change["decided_at"] is not None
    assert _history(sync_engine, item["id"])[-1]["version"] == 3
    accepted = _events(sync_engine, item["id"])[-1]
    assert accepted["event_type"] == "intake.requirement_change.accepted"
    assert accepted["payload"] == {"change_id": str(change["id"]), "version": 3}
    assert [i for i in _list(client, headers, opp["id"]) if i["id"] != item["id"]] == others

    again = _accept(client, headers, opp["id"], body, body["row_version"])
    assert again.status_code == 409, again.text
    assert_problem(again.json(), 409, "no_pending_change")


def test_accept_and_reject_need_a_current_if_match(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)

    missing = _accept(client, headers, opp["id"], item)
    assert missing.status_code == 428, missing.text
    assert_problem(missing.json(), 428, "if_match_required")
    stale = _accept(client, headers, opp["id"], item, item["row_version"] - 1)
    assert stale.status_code == 412, stale.text
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert _reject(client, headers, opp["id"], item, "No.").status_code == 428
    assert (
        _reject(client, headers, opp["id"], item, "No.", item["row_version"] - 1).status_code == 412
    )

    assert _changes(sync_engine, item["id"])[0]["status"] == "open"


def test_reject_records_the_reason_and_keeps_the_requirement(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)

    response = _reject(
        client, headers, opp["id"], item, "  The customer meant ECC.  ", item["row_version"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["text"], body["version"], body["pending_change"]) == ("SAP link.", 2, None)
    assert body["evidence"] == item["evidence"]
    assert body["row_version"] == item["row_version"] + 1
    (change,) = _changes(sync_engine, item["id"])
    assert (change["status"], change["reason"]) == ("rejected", "The customer meant ECC.")
    assert change["decided_by"] is not None
    rejected = _events(sync_engine, item["id"])[-1]
    assert rejected["event_type"] == "intake.requirement_change.rejected"
    assert rejected["payload"] == {"change_id": str(change["id"]), "version": 2}
    assert "ECC" not in str(_events(sync_engine, item["id"]))

    # The same passages proposed again: nothing is written.
    _rerun(db_url, opp, gateway, ("Connect to SAP S/4 HANA!", "integration", SAP_S4[2]), UPTIME)
    assert len(_changes(sync_engine, item["id"])) == 1
    assert _row(sync_engine, item["id"])["row_version"] == body["row_version"]

    nothing = _reject(client, headers, opp["id"], body, "Again.", body["row_version"])
    assert nothing.status_code == 409
    assert_problem(nothing.json(), 409, "no_pending_change")


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_a_blank_or_long_reason_is_422(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway, reason: str
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)

    response = _reject(client, headers, opp["id"], item, reason, item["row_version"])

    assert response.status_code == 422, response.text
    assert_problem(response.json(), 422, "validation_error")
    assert _changes(sync_engine, item["id"])[0]["status"] == "open"


def test_sales_representatives_see_the_change_but_cannot_decide_it(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)
    opp = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    seen = {i["id"]: i for i in _list(client, rep, opp["id"])}[item["id"]]
    assert seen["pending_change"] == item["pending_change"]
    for call in (
        _accept(client, rep, opp["id"], item, item["row_version"]),
        _reject(client, rep, opp["id"], item, "No.", item["row_version"]),
    ):
        assert call.status_code == 403, call.text
        assert_problem(call.json(), 403, "forbidden")
    assert _accept(client, outsider, opp["id"], item, item["row_version"]).status_code == 404
    unknown = {**item, "id": str(uuid4())}
    assert _accept(client, headers, opp["id"], unknown, 1).status_code == 404
    assert _changes(sync_engine, item["id"])[0]["status"] == "open"


def test_the_passage_of_a_pending_change_opens_like_any_evidence(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)
    (chip,) = item["pending_change"]["evidence"]

    response = client.get(f"{BASE}/{opp['id']}/passages/{chip['passage_id']}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "the SAP system is S/4HANA"
    assert all(str(p["id"]) != chip["passage_id"] for p in passages(sync_engine, item["id"]))


# --- review decisions -----------------------------------------------------------------------


def test_a_re_uploaded_source_matches_across_versions_and_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    note = f"{NOTE}{uuid4()}"
    headers, opp, (s1,) = parsed(client, sync_engine, db_url, ("call.txt", note))
    gateway.replies = [out(SAP, UPTIME)]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    items = _list(client, headers, opp["id"])
    before = [_row(sync_engine, i["id"]) for i in items]

    again = upload(client, headers, opp["id"], "call.txt", note)  # S1 v2, the same sentences
    assert (again["id"], again["version"]) == (s1["id"], 2)
    assert drain(db_url, PARSE) == ["succeeded"]
    gateway.replies = [
        out(
            ("Integrate with SAP.", "integration", [("S1", "We must connect to SAP")]),
            ("Available around the clock.", "non_functional", [("S1", "The site runs 24/7")]),
        )
    ]
    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert "S1 kind=note" in gateway.requests[-1].messages[1].content
    assert [_row(sync_engine, i["id"]) for i in items] == before
    assert len(requirements(sync_engine, opp["id"])) == 2  # no duplicates
    for item in items:
        assert len(_history(sync_engine, item["id"])) == 1
        assert _changes(sync_engine, item["id"]) == []
        assert [p["source_version"] for p in passages(sync_engine, item["id"])] == [1]


def test_an_edit_supersedes_the_open_change(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)

    edited = _patch(
        client, headers, opp["id"], item, {"text": "SAP ECC link."}, item["row_version"]
    )

    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["text"], body["version"], body["pending_change"]) == ("SAP ECC link.", 3, None)
    (change,) = _changes(sync_engine, item["id"])
    assert (change["status"], change["decided_by"], change["reason"]) == ("superseded", None, None)


def test_a_confirm_leaves_the_open_change_open(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, item = _locked_with_change(client, sync_engine, db_url, gateway)

    confirmed = _confirm(client, headers, opp["id"], item, item["row_version"])

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["pending_change"] == item["pending_change"]
    assert _changes(sync_engine, item["id"])[0]["status"] == "open"
