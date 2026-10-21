"""Shaping the Requirement list (Story 2.6 remainder): `POST …/requirements` (create),
`POST …/requirements/{id}/delete`, `POST …/requirements/{id}/split` and
`POST …/requirements/merge`, the stable `R<n>` numbers, and re-extraction after a delete or
split, against a real, migrated Postgres as psa_app, with the fake ModelGateway of
`test_intake_extraction.py`."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.intake.domain.requirements import Classification as C
from app.modules.intake.domain.requirements import (
    ExistingRequirement,
    PassageKey,
    ReconcileOutcome,
    ReconcileProposal,
    delete_reason,
    reconcile,
)
from tests import test_gaps_detection as gaps_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_health import assert_problem
from tests.test_intake_extraction import (
    BASE,
    DETECT,
    EXTRACT,
    FakeGateway,
    drain,
    out,
    parsed,
    passages,
    requirements,
)
from tests.test_intake_incremental import (
    SAP,
    SAP_S4,
    UPTIME,
    _changes,
    _first_run,
    _locked_with_change,
    _new_source,
    _rerun,
)
from tests.test_intake_parse_job import _alembic
from tests.test_intake_requirement_edits import ITEMS, NOTE, _events, _history, _list, _row
from tests.test_opportunities import PSE, _add, _if_match, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = gaps_tests._chat_profile

# One Requirement citing two passages of the note.
SAP_SSO = (
    "Connect to SAP with single sign-on.",
    "integration",
    [("S1", "We must connect to SAP"), ("S1", "Single sign-on is required")],
)


# --- helpers --------------------------------------------------------------------------------


def _create(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    text: str = "Support returns.",
    classification: str = "functional",
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/requirements",
        headers=headers,
        json={"text": text, "classification": classification},
    )


def _delete(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    reason: str = "Not in scope.",
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.post(
        f"{BASE}/{opp_id}/requirements/{item['id']}/delete",
        headers={**headers, **extra},
        json={"reason": reason},
    )


def _split(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    parts: list[tuple[str, str]],
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.post(
        f"{BASE}/{opp_id}/requirements/{item['id']}/split",
        headers={**headers, **extra},
        json={"parts": [{"text": t, "classification": c} for t, c in parts]},
    )


TWO_PARTS = [("Connect to SAP.", "integration"), ("Single sign-on.", "security")]


def _merge(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    refs: list[tuple[str, int]],
    text: str = "Merged.",
    classification: str = "integration",
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/requirements/merge",
        headers=headers,
        json={
            "requirements": [{"id": i, "row_version": v} for i, v in refs],
            "text": text,
            "classification": classification,
        },
    )


def _extracted(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, *items: Any
) -> tuple[dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    headers, opp, _ = parsed(client, engine, db_url, ("n.txt", f"{NOTE}{uuid4()}"))
    gateway.replies = [out(*items)]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    return headers, opp, _list(client, headers, opp["id"])


def _passage_ids(engine: Engine, requirement_id: Any) -> set[UUID]:
    return {p["id"] for p in passages(engine, requirement_id)}


def _numbers(items: list[dict[str, Any]]) -> dict[str, int]:
    return {i["text"]: i["number"] for i in items}


# --- domain ---------------------------------------------------------------------------------

S1 = UUID("00000000-0000-7000-8000-000000000001")


def _key(start: int, end: int) -> PassageKey:
    return PassageKey(S1, 1, start, end)


def test_a_proposal_matching_a_deleted_requirement_is_removed() -> None:
    gone = ExistingRequirement(uuid4(), "Old.", "functional", True, (_key(0, 10),))
    kept = ExistingRequirement(uuid4(), "Kept.", "functional", False, (_key(20, 30),))
    again = ReconcileProposal("Old, reworded.", C.FUNCTIONAL, (_key(2, 8), _key(40, 50)))
    same_text = ReconcileProposal("old.", C.DATA, (_key(60, 70),))
    new = ReconcileProposal("New.", C.DATA, (_key(80, 90),))

    a, b, c = reconcile([again, same_text, new], [kept], [gone])

    assert (a.outcome, a.requirement_id, a.new_passages) == (ReconcileOutcome.REMOVED, gone.id, ())
    # One-to-one: the text fallback can't take the deleted one twice.
    assert b.outcome is ReconcileOutcome.ADD
    assert c.outcome is ReconcileOutcome.ADD


def test_an_active_requirement_wins_a_tie_with_a_deleted_one() -> None:
    gone = ExistingRequirement(uuid4(), "A.", "functional", True, (_key(0, 10),))
    part = ExistingRequirement(uuid4(), "A part.", "functional", True, (_key(0, 10),))

    (step,) = reconcile([ReconcileProposal("A.", C.FUNCTIONAL, (_key(0, 10),))], [part], [gone])

    assert (step.outcome, step.requirement_id) == (ReconcileOutcome.UNCHANGED, part.id)


def test_the_delete_reason_follows_the_reject_rule() -> None:
    assert delete_reason("  Duplicate. ") == "Duplicate."
    for bad in ("", "  ", "x" * 501):
        with pytest.raises(ValueError):
            delete_reason(bad)


# --- create ---------------------------------------------------------------------------------


def test_create_adds_a_locked_human_requirement_without_evidence(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, items = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])

    response = _create(client, headers, opp["id"], "  Support returns.  ", "functional")

    assert response.status_code == 201, response.text
    body = response.json()
    assert response.headers["ETag"] == f'"{body["row_version"]}"'
    assert (body["text"], body["classification"], body["origin"]) == (
        "Support returns.",
        "functional",
        "human",
    )
    assert (body["version"], body["locked_by_human"], body["number"]) == (1, True, 3)
    assert (body["evidence"], body["confirmed_at"], body["pending_change"]) == ([], None, None)
    assert body["last_changed_by"]["name"] == "Owner Person"
    assert [i["id"] for i in _list(client, headers, opp["id"])] == [
        *[i["id"] for i in items],
        body["id"],
    ]
    (v1,) = _history(sync_engine, body["id"])
    assert (v1["version"], v1["text"]) == (1, "Support returns.")
    (event,) = _events(sync_engine, body["id"])
    assert (event["event_type"], event["payload"], event["subject_version"]) == (
        "intake.requirement.created",
        {"version": 1},
        1,
    )
    assert _row(sync_engine, body["id"])["extraction_id"] is None


@pytest.mark.parametrize(
    ("text", "classification"),
    [("", "functional"), ("   ", "data"), ("x" * 2001, "data"), ("Fine.", "unknown")],
)
def test_invalid_creates_are_422_and_write_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    text: str,
    classification: str,
) -> None:
    headers, opp, items = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:1])

    response = _create(client, headers, opp["id"], text, classification)

    assert response.status_code == 422, response.text
    assert_problem(response.json(), 422, "validation_error")
    assert len(_list(client, headers, opp["id"])) == len(items)


def test_numbers_are_never_reused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (r1, r2) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])
    assert _delete(client, headers, opp["id"], r2, version=r2["row_version"]).status_code == 200

    created = _create(client, headers, opp["id"]).json()

    assert created["number"] == 3
    assert _numbers(_list(client, headers, opp["id"])) == {r1["text"]: 1, "Support returns.": 3}


# --- delete ---------------------------------------------------------------------------------


def test_delete_removes_it_from_the_list_and_keeps_the_reason_out_of_the_trace(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])

    response = _delete(client, headers, opp["id"], uptime, " Out of scope. ", uptime["row_version"])

    assert response.status_code == 200, response.text
    assert response.json() == {"id": uptime["id"], "status": "deleted", "version": 1}
    assert [i["id"] for i in _list(client, headers, opp["id"])] == [sap["id"]]
    row = _row(sync_engine, uptime["id"])
    assert (row["status"], row["removal_reason"], row["number"]) == ("deleted", "Out of scope.", 2)
    assert len(_history(sync_engine, uptime["id"])) == 1  # still in history
    (event,) = _events(sync_engine, uptime["id"])
    assert (event["event_type"], event["payload"]) == ("intake.requirement.deleted", {"version": 1})
    assert "scope" not in str(event)


def test_delete_needs_a_current_if_match_and_a_reason(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap,) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:1])

    stale = _delete(client, headers, opp["id"], sap, version=sap["row_version"] + 1)
    huge = _delete(client, headers, opp["id"], sap, version=2**31)
    missing = _delete(client, headers, opp["id"], sap)
    blank = _delete(client, headers, opp["id"], sap, "   ", sap["row_version"])
    long = _delete(client, headers, opp["id"], sap, "x" * 501, sap["row_version"])
    unknown = _delete(client, headers, opp["id"], {"id": str(uuid4())}, version=1)

    for response in (stale, huge):
        assert_problem(response.json(), 412, "row_version_mismatch")
    assert_problem(missing.json(), 428, "if_match_required")
    for response in (blank, long):
        assert_problem(response.json(), 422, "validation_error")
    assert blank.json()["detail"] == "Give a reason for deleting the Requirement."
    assert_problem(unknown.json(), 404, "not_found")
    assert _row(sync_engine, sap["id"])["status"] == "active"
    assert _events(sync_engine, sap["id"]) == []


def test_a_removed_requirement_is_404_for_every_command(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])
    deleted = _delete(client, headers, opp["id"], sap, version=sap["row_version"])
    assert deleted.status_code == 200

    gone = sap["row_version"] + 1
    responses = [
        _delete(client, headers, opp["id"], sap, version=gone),
        _split(client, headers, opp["id"], sap, TWO_PARTS, gone),
        _merge(client, headers, opp["id"], [(sap["id"], gone), (uptime["id"], 1)]),
        client.patch(
            f"{BASE}/{opp['id']}/requirements/{sap['id']}",
            headers={**headers, **_if_match(gone)},
            json={"text": "Back."},
        ),
    ]

    for response in responses:
        assert_problem(response.json(), 404, "not_found")
    assert _row(sync_engine, uptime["id"])["status"] == "active"


# --- split ----------------------------------------------------------------------------------


def test_split_makes_two_locked_requirements_citing_all_the_evidence(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (both, uptime) = _extracted(
        client, sync_engine, db_url, gateway, SAP_SSO, ITEMS[1]
    )
    cited = _passage_ids(sync_engine, both["id"])
    assert len(cited) == 2

    response = _split(client, headers, opp["id"], both, TWO_PARTS, both["row_version"])

    assert response.status_code == 201, response.text
    first, second = response.json()["items"]
    for part, (text, classification), number in (
        (first, TWO_PARTS[0], 3),
        (second, TWO_PARTS[1], 4),
    ):
        assert (part["text"], part["classification"], part["number"]) == (
            text,
            classification,
            number,
        )
        assert (part["origin"], part["locked_by_human"], part["version"]) == ("human", True, 1)
        assert part["confirmed_at"] is None
        assert len(part["evidence"]) == 2
        assert _passage_ids(sync_engine, part["id"]) == cited
        assert _events(sync_engine, part["id"]) == []
    assert _row(sync_engine, both["id"])["status"] == "superseded"
    assert [i["id"] for i in _list(client, headers, opp["id"])] == [
        uptime["id"],
        first["id"],
        second["id"],
    ]
    (event,) = _events(sync_engine, both["id"])
    assert (event["event_type"], event["payload"], event["subject_version"]) == (
        "intake.requirement.split",
        {"version": 1, "into": [first["id"], second["id"]]},
        1,
    )


def test_split_checks_its_if_match_and_parts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap,) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:1])
    version = sap["row_version"]

    stale = _split(client, headers, opp["id"], sap, TWO_PARTS, version + 1)
    missing = _split(client, headers, opp["id"], sap, TWO_PARTS)
    three = _split(client, headers, opp["id"], sap, [*TWO_PARTS, ("Third.", "data")], version)
    one = _split(client, headers, opp["id"], sap, TWO_PARTS[:1], version)
    blank = _split(client, headers, opp["id"], sap, [("A.", "data"), (" ", "data")], version)

    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert_problem(missing.json(), 428, "if_match_required")
    for response in (three, one, blank):
        assert_problem(response.json(), 422, "validation_error")
    assert blank.json()["detail"] == "The Requirement text can't be blank."
    assert len(requirements(sync_engine, opp["id"])) == 1
    assert _row(sync_engine, sap["id"])["row_version"] == version


# --- merge ----------------------------------------------------------------------------------


def test_merge_makes_one_requirement_citing_the_union_of_the_evidence(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime, peak) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:3])
    union = _passage_ids(sync_engine, sap["id"]) | _passage_ids(sync_engine, uptime["id"])

    response = _merge(
        client,
        headers,
        opp["id"],
        [(sap["id"], sap["row_version"]), (uptime["id"], uptime["row_version"])],
        "  SAP, around the clock. ",
        "integration",
    )

    assert response.status_code == 201, response.text
    merged = response.json()
    assert response.headers["ETag"] == f'"{merged["row_version"]}"'
    assert (merged["text"], merged["number"], merged["origin"]) == (
        "SAP, around the clock.",
        4,
        "human",
    )
    assert (merged["locked_by_human"], merged["version"], merged["confirmed_at"]) == (
        True,
        1,
        None,
    )
    assert _passage_ids(sync_engine, merged["id"]) == union
    for original in (sap, uptime):
        assert _row(sync_engine, original["id"])["status"] == "superseded"
        assert _events(sync_engine, original["id"]) == []
    assert [i["id"] for i in _list(client, headers, opp["id"])] == [peak["id"], merged["id"]]
    (event,) = _events(sync_engine, merged["id"])
    assert (event["event_type"], event["payload"]) == (
        "intake.requirement.merged",
        {"from": [{"id": sap["id"], "version": 1}, {"id": uptime["id"], "version": 1}]},
    )


def test_one_stale_row_version_fails_the_whole_merge(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])

    stale = _merge(
        client,
        headers,
        opp["id"],
        [(sap["id"], sap["row_version"]), (uptime["id"], uptime["row_version"] + 1)],
    )
    huge = _merge(
        client, headers, opp["id"], [(sap["id"], sap["row_version"]), (uptime["id"], 2**31)]
    )

    for response in (stale, huge):
        assert_problem(response.json(), 412, "row_version_mismatch")
    assert [r["status"] for r in requirements(sync_engine, opp["id"])] == ["active", "active"]
    assert requirements(sync_engine, opp["id"], "superseded") == []


def test_merge_needs_two_to_twenty_distinct_requirements(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])
    current = (sap["id"], sap["row_version"])

    one = _merge(client, headers, opp["id"], [current])
    twice = _merge(client, headers, opp["id"], [current, current])
    many = _merge(client, headers, opp["id"], [(str(uuid4()), 1) for _ in range(21)])
    blank = _merge(
        client, headers, opp["id"], [current, (uptime["id"], uptime["row_version"])], " "
    )
    unknown = _merge(client, headers, opp["id"], [current, (str(uuid4()), 1)])

    for response in (one, twice, many, blank):
        assert_problem(response.json(), 422, "validation_error")
    assert twice.json()["detail"] == "Each Requirement can be merged only once."
    assert_problem(unknown.json(), 404, "not_found")
    assert len(requirements(sync_engine, opp["id"])) == 2


# --- pending changes ------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["delete", "split", "merge"])
def test_removing_a_requirement_supersedes_its_open_change(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway, command: str
) -> None:
    headers, opp, sap = _locked_with_change(client, sync_engine, db_url, gateway)
    assert sap["pending_change"] is not None
    version = sap["row_version"]

    if command == "delete":
        response = _delete(client, headers, opp["id"], sap, version=version)
    elif command == "split":
        response = _split(client, headers, opp["id"], sap, TWO_PARTS, version)
    else:
        other = next(i for i in _list(client, headers, opp["id"]) if i["id"] != sap["id"])
        response = _merge(
            client, headers, opp["id"], [(sap["id"], version), (other["id"], other["row_version"])]
        )

    assert response.is_success, response.text
    assert [c["status"] for c in _changes(sync_engine, sap["id"])] == ["superseded"]
    assert all(i["pending_change"] is None for i in _list(client, headers, opp["id"]))


# --- re-extraction --------------------------------------------------------------------------


def test_re_extraction_never_revives_a_deleted_requirement(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _first_run(client, sync_engine, db_url, gateway)
    assert _delete(client, headers, opp["id"], uptime, version=uptime["row_version"]).is_success
    before = _row(sync_engine, uptime["id"])

    # The model proposes its passages again, reworded.
    _rerun(db_url, opp, gateway, SAP, ("Available around the clock.", "non_functional", UPTIME[2]))

    assert [i["id"] for i in _list(client, headers, opp["id"])] == [sap["id"]]
    assert len(requirements(sync_engine, opp["id"], "deleted")) == 1
    assert _row(sync_engine, uptime["id"]) == before
    assert len(requirements(sync_engine, opp["id"])) == 1


def test_a_new_source_refining_a_split_part_proposes_a_change_to_it(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _first_run(client, sync_engine, db_url, gateway)
    parts = [("Connect to SAP.", "integration"), ("Use the SAP test system.", "integration")]
    first, second = _split(client, headers, opp["id"], sap, parts, sap["row_version"]).json()[
        "items"
    ]

    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME)

    after = {i["id"]: i for i in _list(client, headers, opp["id"])}
    assert set(after) == {uptime["id"], first["id"], second["id"]}
    change = after[first["id"]]["pending_change"]
    assert change is not None
    assert change["text"] == SAP_S4[0]
    assert after[first["id"]]["text"] == "Connect to SAP."
    assert after[second["id"]]["pending_change"] is None
    assert after[uptime["id"]] == uptime


# --- stable numbers -------------------------------------------------------------------------


def test_numbers_stay_after_delete_and_split_and_gaps_keep_their_labels(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, items = _extracted(client, sync_engine, db_url, gateway, *ITEMS)
    assert [i["number"] for i in items] == [1, 2, 3, 4, 5]
    gateway.replies = [gaps_tests.gaps_out(gaps_tests.gap("SSO provider", ["R4"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    r1, r2, r3, r4, r5 = items

    assert _delete(client, headers, opp["id"], r2, version=r2["row_version"]).is_success
    split = _split(client, headers, opp["id"], r3, TWO_PARTS, r3["row_version"])
    assert split.status_code == 201, split.text

    listed = _list(client, headers, opp["id"])
    assert {i["id"]: i["number"] for i in listed} == {
        r1["id"]: 1,
        r4["id"]: 4,
        r5["id"]: 5,
        **{part["id"]: n for part, n in zip(split.json()["items"], (6, 7), strict=True)},
    }
    assert [i["number"] for i in listed] == [1, 4, 5, 6, 7]
    (gap,) = client.get(f"{BASE}/{opp['id']}/gaps", headers=headers).json()["items"]
    assert [(r["id"], r["label"]) for r in gap["requirements"]] == [(r4["id"], "R4")]


def test_numbers_are_unique_per_opportunity(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:1])
    with sync_engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO intake_requirements (id, opportunity_id, text, classification, "
                "origin, locked_by_human, status, version, row_version, number) VALUES "
                "(:i, :o, 'Dup.', 'data', 'human', true, 'active', 1, 1, 1)"
            ),
            {"i": uuid4(), "o": opp["id"]},
        )


# --- who ------------------------------------------------------------------------------------


def _every_command(
    client: TestClient, headers: dict[str, str], opp_id: str, a: dict[str, Any], b: dict[str, Any]
) -> list[Any]:
    return [
        _create(client, headers, opp_id),
        _delete(client, headers, opp_id, a, version=a["row_version"]),
        _split(client, headers, opp_id, a, TWO_PARTS, a["row_version"]),
        _merge(client, headers, opp_id, [(a["id"], a["row_version"]), (b["id"], b["row_version"])]),
    ]


def test_sales_reps_and_readers_are_403_and_outsiders_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime) = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    for who, status, code in ((rep, 403, "forbidden"), (reader, 403, "forbidden")):
        for response in _every_command(client, who, opp["id"], sap, uptime):
            assert response.status_code == status, response.text
            assert_problem(response.json(), status, code)
    for response in _every_command(client, outsider, opp["id"], sap, uptime):
        assert_problem(response.json(), 404, "not_found")
    assert [i["id"] for i in _list(client, headers, opp["id"])] == [sap["id"], uptime["id"]]
    assert _events(sync_engine, sap["id"]) == []


def test_a_presales_collaborator_may_shape_the_list(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = _extracted(client, sync_engine, db_url, gateway, *ITEMS[:2])
    pse, pse_id = _user(client, sync_engine, "Colleague Person", PSE)
    assert _add(client, headers, opp, pse_id).status_code == 200

    created = _create(client, pse, opp["id"])

    assert created.status_code == 201, created.text
    assert created.json()["last_changed_by"] == {"id": str(pse_id), "name": "Colleague Person"}


# --- acceptance -----------------------------------------------------------------------------


def test_split_merge_delete_create_then_a_re_extraction_keeps_the_shape(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    # R1 cites SAP and SSO; R2 and R3 say the same; R4 is wrong; R5 stays.
    duplicate_a = ("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")])
    duplicate_b = ("Always on.", "non_functional", [("S1", "Peak is 900 orders per hour")])
    wrong = ("Prices in USD.", "commercial", [("S1", "Pricing in EUR")])
    keep = ("Peak 900 orders/hour.", "functional", [("S1", "Peak is 900 orders per hour")])
    items = (SAP_SSO, duplicate_a, duplicate_b, wrong, keep)
    headers, opp, (r1, r2, r3, r4, r5) = _extracted(client, sync_engine, db_url, gateway, *items)
    opp_id = opp["id"]

    split = _split(client, headers, opp_id, r1, TWO_PARTS, r1["row_version"]).json()["items"]
    merged = _merge(
        client,
        headers,
        opp_id,
        [(r2["id"], r2["row_version"]), (r3["id"], r3["row_version"])],
        "Available around the clock.",
        "non_functional",
    ).json()
    assert _delete(client, headers, opp_id, r4, "Wrong currency.", r4["row_version"]).is_success
    added = _create(client, headers, opp_id, "Support returns.", "functional").json()

    expected = {
        r5["id"]: (5, "Peak 900 orders/hour."),
        split[0]["id"]: (6, "Connect to SAP."),
        split[1]["id"]: (7, "Single sign-on."),
        merged["id"]: (8, "Available around the clock."),
        added["id"]: (9, "Support returns."),
    }
    shaped = _list(client, headers, opp_id)
    assert {i["id"]: (i["number"], i["text"]) for i in shaped} == expected
    evidence = {i["id"]: _passage_ids(sync_engine, i["id"]) for i in shaped}
    assert (
        evidence[split[0]["id"]] == evidence[split[1]["id"]] == _passage_ids(sync_engine, r1["id"])
    )
    assert evidence[merged["id"]] == _passage_ids(sync_engine, r2["id"]) | _passage_ids(
        sync_engine, r3["id"]
    )
    assert evidence[added["id"]] == set()

    # The same Sources again: the deleted one stays deleted and nothing else changes. The
    # merged duplicates come back as one Requirement citing both passages.
    combined = (
        "Runs 24/7 at peak.",
        "non_functional",
        [("S1", "The site runs 24/7"), ("S1", "Peak is 900 orders per hour")],
    )
    _rerun(db_url, opp, gateway, SAP_SSO, combined, wrong, keep)

    assert _list(client, headers, opp_id) == shaped
    assert _row(sync_engine, r4["id"])["status"] == "deleted"


# --- migration 0034 -------------------------------------------------------------------------


def test_migration_backfills_numbers_and_downgrades_deleted_to_superseded(
    sync_engine: Engine,
) -> None:
    opportunity_id = uuid4()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # (id, status, created_at offset): active ones number first, then the inactive ones.
    rows = [
        (uuid4(), "superseded", 0),
        (uuid4(), "active", 1),
        (uuid4(), "active", 2),
        (uuid4(), "superseded", 3),
    ]
    deleted_id = uuid4()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO intake_requirements (id, opportunity_id, text, classification, "
                "origin, locked_by_human, status, version, row_version, number, "
                "removal_reason) VALUES (:i, :o, 'Gone.', 'data', 'human', true, 'deleted', 1, "
                "1, 99, 'Wrong.')"
            ),
            {"i": deleted_id, "o": opportunity_id},
        )
    _alembic("downgrade", "0033_conflict_agent")
    try:
        with sync_engine.begin() as conn:
            assert (
                conn.execute(
                    sa.text("SELECT status FROM intake_requirements WHERE id = :i"),
                    {"i": deleted_id},
                ).scalar_one()
                == "superseded"
            )
            for requirement_id, status, offset in rows:
                conn.execute(
                    sa.text(
                        "INSERT INTO intake_requirements (id, opportunity_id, text, "
                        "classification, origin, locked_by_human, status, version, "
                        "row_version, created_at) VALUES (:i, :o, 'T.', 'data', 'extracted', "
                        "false, :s, 1, 1, :c)"
                    ),
                    {
                        "i": requirement_id,
                        "o": opportunity_id,
                        "s": status,
                        "c": base + timedelta(minutes=offset),
                    },
                )
    finally:
        _alembic("upgrade", "head")

    with sync_engine.connect() as conn:
        numbers = dict(
            conn.execute(
                sa.text("SELECT id, number FROM intake_requirements WHERE opportunity_id = :o"),
                {"o": opportunity_id},
            ).all()
        )
    old, first, second, later = (r[0] for r in rows)
    # The once-deleted row (now superseded, created last) numbers after the others.
    assert numbers == {first: 1, second: 2, old: 3, later: 4, deleted_id: 5}


# --- review decisions (Story 2.6 review loop 1) ---------------------------------------------


def test_re_extraction_never_revives_a_merged_duplicate(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    duplicate_a = ("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")])
    duplicate_b = ("Always on.", "non_functional", [("S1", "Peak is 900 orders per hour")])
    headers, opp, (_, a, b) = _extracted(
        client, sync_engine, db_url, gateway, SAP, duplicate_a, duplicate_b
    )
    merged = _merge(
        client,
        headers,
        opp["id"],
        [(a["id"], a["row_version"]), (b["id"], b["row_version"])],
        "Available around the clock.",
        "non_functional",
    )
    assert merged.status_code == 201, merged.text
    for original in (a, b):
        row = _row(sync_engine, original["id"])
        assert (row["status"], row["locked_by_human"]) == ("superseded", True)
    shaped = _list(client, headers, opp["id"])

    # The identical output again: the duplicates as two separate proposals.
    _rerun(db_url, opp, gateway, SAP, duplicate_a, duplicate_b)

    assert _list(client, headers, opp["id"]) == shaped
    assert len(requirements(sync_engine, opp["id"])) == 2


def test_re_extraction_never_revives_a_split_original(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (both,) = _extracted(client, sync_engine, db_url, gateway, SAP_SSO)
    assert _split(client, headers, opp["id"], both, TWO_PARTS, both["row_version"]).is_success
    shaped = _list(client, headers, opp["id"])

    _rerun(db_url, opp, gateway, SAP_SSO, SAP_SSO)

    assert _list(client, headers, opp["id"]) == shaped


def test_accepting_a_pending_change_clears_the_confirmation(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, sap = _locked_with_change(client, sync_engine, db_url, gateway)
    confirmed = client.post(
        f"{BASE}/{opp['id']}/requirements/{sap['id']}/confirm",
        headers={**headers, **_if_match(sap["row_version"])},
    ).json()
    assert confirmed["confirmed_at"] is not None

    accepted = client.post(
        f"{BASE}/{opp['id']}/requirements/{sap['id']}/change/accept",
        headers={**headers, **_if_match(confirmed["row_version"])},
    )

    assert accepted.status_code == 200, accepted.text
    assert (accepted.json()["confirmed_at"], accepted.json()["confirmed_by"]) == (None, None)
    row = _row(sync_engine, sap["id"])
    assert (row["confirmed_at"], row["confirmed_by"]) == (None, None)


def test_a_text_only_match_with_a_removed_requirement_is_removed() -> None:
    gone = ExistingRequirement(uuid4(), "Runs  24/7.", "non_functional", True, ())

    (step,) = reconcile([ReconcileProposal("runs 24/7.", C.DATA, (_key(0, 10),))], [], [gone])

    assert (step.outcome, step.requirement_id) == (ReconcileOutcome.REMOVED, gone.id)


def test_a_requirement_removed_while_extraction_reconciles_it_is_skipped(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.intake.adapters import requirements_repository as repo

    headers, opp, (sap, uptime) = _first_run(client, sync_engine, db_url, gateway)
    original = repo.version_extracted

    async def removed_first(*args: Any, **kwargs: Any) -> Any:
        # A person deletes the unlocked Requirement after the reconcile read it.
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE intake_requirements SET status = 'deleted', removal_reason = 'x', "
                    "locked_by_human = true, row_version = row_version + 1 WHERE id = :i"
                ),
                {"i": sap["id"]},
            )
        return await original(*args, **kwargs)

    monkeypatch.setattr(repo, "version_extracted", removed_first)

    # The new Source refines the unlocked SAP Requirement (a version bump); the extraction
    # still succeeds (`_new_source` asserts it) and writes nothing for it.
    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME)

    assert [i["id"] for i in _list(client, headers, opp["id"])] == [uptime["id"]]
    assert _changes(sync_engine, sap["id"]) == []
    assert _row(sync_engine, sap["id"])["version"] == 1
