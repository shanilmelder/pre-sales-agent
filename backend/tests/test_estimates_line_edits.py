"""Editing an Estimate line's hours and role mix (Story 8.2, demo slice) against a real,
migrated Postgres as psa_app: `PATCH …/estimate-lines/{line_id}` (validation, rounding,
no-op, If-Match, superseded versions, who may), the recalculated totals, the trace, carrying
edits onto a re-draft's matching lines, and the column-level grants.

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no other
claimer takes them, and `drain` runs only the current test's Opportunities' jobs.
"""

import logging
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_estimates_assumptions as assumption_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_estimates_draft import SIX, detected, est_line, line_rows, lines_out, versions
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DRAFT, FakeGateway, drain
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_proposal_profile = assumption_tests._proposal_profile

REASON = "Reuse the existing connector"
MIX_RULE = "Role mix must name every role and add up to 100%."
EDITED = "estimates.estimate_line.edited"


def drafted(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with 5 Requirements and a draft Estimate v1 of the SIX lines."""
    headers, opp = detected(client, engine, db_url, gateway)
    gateway.replies = [lines_out(*SIX)]
    assert drain(db_url, DRAFT) == ["succeeded"]
    return headers, opp


def _estimate(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/{opp_id}/estimate", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _lines(version: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["title"]: line for s in version["sections"] for line in s["lines"]}


def _line(client: TestClient, headers: dict[str, str], opp_id: str, title: str) -> dict[str, Any]:
    return _lines(_estimate(client, headers, opp_id)["version"])[title]


def _edit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    line_id: str,
    body: dict[str, Any],
    row_version: int | None = 1,
) -> Any:
    extra = {} if row_version is None else {"If-Match": f'"{row_version}"'}
    return client.patch(
        f"{BASE}/{opp_id}/estimate-lines/{line_id}", headers={**headers, **extra}, json=body
    )


def edited_events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :t "
        "ORDER BY occurred_at, id",
        o=opp_id,
        t=EDITED,
    )


def redraft(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    db_url: str,
    gateway: FakeGateway,
    lines: tuple[dict[str, Any], ...] = SIX,
) -> None:
    started = client.post(f"{BASE}/{opp_id}/estimate-drafts", headers=headers)
    assert started.status_code == 201, started.text
    gateway.replies = [lines_out(*lines)]
    assert drain(db_url, DRAFT) == ["succeeded"]


# --- editing --------------------------------------------------------------------------------


def test_editing_the_hours_recalculates_and_traces(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    before = _estimate(client, headers, opp["id"])["version"]
    sap = _lines(before)["SAP order interface"]
    assert (sap["effort_hours"], sap["row_version"], sap["edited"]) == (40.0, 1, False)
    assert (sap["edited_by_name"], sap["edited_at"], sap["edit_reason"]) == (None, None, None)
    assert before["totals"]["effort_hours"] == 108.5

    with caplog.at_level(logging.DEBUG):
        response = _edit(
            client, headers, opp["id"], sap["id"], {"effort_hours": 32, "reason": f"  {REASON} "}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_edit_lines"] is True
    version = body["version"]
    line = _lines(version)["SAP order interface"]
    assert (line["effort_hours"], line["total_hours"]) == (32.0, 32.0)
    assert line["role_mix"] == {"engineer": 60, "project_manager": 20, "qa": 20}
    assert line["role_hours"] == {"engineer": 19.2, "project_manager": 6.4, "qa": 6.4}
    assert (line["edited"], line["edited_by_name"], line["edit_reason"]) == (
        True,
        "Owner Person",
        REASON,
    )
    assert line["edited_at"] is not None
    assert (line["row_version"], line["edit_carried_from_version"]) == (2, None)
    integration = next(s for s in version["sections"] if s["section"] == "integration")
    assert integration["subtotal"]["effort_hours"] == 32.0
    assert version["totals"]["effort_hours"] == 100.5
    assert version["totals"]["total_hours"] == 100.5
    engineer = before["totals"]["role_hours"]["engineer"] - 4.8
    assert version["totals"]["role_hours"]["engineer"] == pytest.approx(engineer)
    assert body == _estimate(client, headers, opp["id"])  # the same read model

    (event,) = edited_events(sync_engine, opp["id"])
    assert (event["subject_type"], str(event["subject_id"])) == (
        "estimates.estimate_line",
        sap["id"],
    )
    assert (event["actor_type"], event["subject_version"]) == ("user", 2)
    assert event["payload"] == {
        "version": 1,
        "before_hours": 40.0,
        "after_hours": 32.0,
        "before_role_mix": {"engineer": 60, "project_manager": 20, "qa": 20},
        "after_role_mix": {"engineer": 60, "project_manager": 20, "qa": 20},
        "reason": REASON,
    }
    (stored,) = [r for r in line_rows(sync_engine, before["id"]) if str(r["id"]) == sap["id"]]
    assert (stored["edit_reason"], stored["row_version"]) == (REASON, 2)

    # Privacy: neither the reason nor the line's title is logged.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    assert REASON not in logged
    assert "SAP order interface" not in logged


def test_editing_the_role_mix_recalculates_the_role_hours(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    before = _estimate(client, headers, opp["id"])["version"]
    sap = _lines(before)["SAP order interface"]

    mix = {"engineer": 40, "project_manager": 40, "qa": 20}
    response = _edit(client, headers, opp["id"], sap["id"], {"role_mix": mix, "reason": REASON})

    assert response.status_code == 200, response.text
    version = response.json()["version"]
    line = _lines(version)["SAP order interface"]
    assert (line["effort_hours"], line["role_mix"]) == (40.0, mix)
    assert line["role_hours"] == {"engineer": 16.0, "project_manager": 16.0, "qa": 8.0}
    old, new = before["totals"]["role_hours"], version["totals"]["role_hours"]
    assert new["engineer"] == pytest.approx(old["engineer"] - 8.0)
    assert new["project_manager"] == pytest.approx(old["project_manager"] + 8.0)
    assert new["qa"] == old["qa"]
    assert version["totals"]["effort_hours"] == before["totals"]["effort_hours"]
    (event,) = edited_events(sync_engine, opp["id"])
    assert event["payload"]["before_role_mix"] == {
        "engineer": 60,
        "project_manager": 20,
        "qa": 20,
    }
    assert event["payload"]["after_role_mix"] == mix
    assert event["payload"]["before_hours"] == event["payload"]["after_hours"] == 40.0


def test_hours_and_mix_together_and_rounding_half_up(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")

    body = {"effort_hours": 12.25, "role_mix": {"engineer": 100, "project_manager": 0, "qa": 0}}
    response = _edit(client, headers, opp["id"], sap["id"], {**body, "reason": REASON})

    assert response.status_code == 200, response.text
    line = _lines(response.json()["version"])["SAP order interface"]
    assert line["effort_hours"] == 12.3
    assert line["role_hours"] == {"engineer": 12.3, "project_manager": 0.0, "qa": 0.0}
    # Zero hours is allowed.
    zero = _edit(client, headers, opp["id"], sap["id"], {"effort_hours": 0, "reason": "Out"}, 2)
    assert zero.status_code == 200, zero.text
    assert _lines(zero.json()["version"])["SAP order interface"]["total_hours"] == 0.0


@pytest.mark.parametrize(
    "mix",
    [
        {"engineer": 50, "project_manager": 30, "qa": 10},  # 90
        {"engineer": 80, "project_manager": 20},  # a role missing
        {"engineer": 33.5, "project_manager": 33, "qa": 33.5},  # fractions
        {"engineer": 50, "project_manager": 30, "qa": 20, "architect": 0},  # an unknown role
        {"engineer": 120, "project_manager": -10, "qa": -10},  # out of range
        {"engineer": True, "project_manager": 50, "qa": 49},  # not a number
    ],
    ids=["sum-90", "missing", "fraction", "extra", "range", "bool"],
)
def test_a_bad_role_mix_is_refused(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    mix: dict[str, Any],
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")

    response = _edit(client, headers, opp["id"], sap["id"], {"role_mix": mix, "reason": REASON})

    assert response.status_code == 422, response.text
    assert_problem(response.json(), 422, "validation_error")
    assert response.json()["detail"] == MIX_RULE
    assert _line(client, headers, opp["id"], "SAP order interface") == sap
    assert edited_events(sync_engine, opp["id"]) == []


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (
            {"effort_hours": -1, "reason": REASON},
            "Effort must be a number of hours from 0 to 2,000.",
        ),
        (
            {"effort_hours": 2500, "reason": REASON},
            "Effort must be a number of hours from 0 to 2,000.",
        ),
        ({"effort_hours": 32, "reason": "   "}, "Give a reason of 1 to 300 characters."),
        ({"effort_hours": 32, "reason": "x" * 301}, "Give a reason of 1 to 300 characters."),
        ({"reason": REASON}, "Change the effort or the role mix."),
        ({"effort_hours": 32}, None),  # no reason at all
        ({"effort_hours": "32", "reason": REASON}, None),  # not a number
        ({"effort_hours": 32, "reason": REASON, "title": "x"}, None),  # not editable
    ],
    ids=[
        "negative",
        "too-many",
        "blank-reason",
        "long-reason",
        "nothing",
        "no-reason",
        "text",
        "title",
    ],
)
def test_a_bad_value_is_refused(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    body: dict[str, Any],
    detail: str | None,
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")

    response = _edit(client, headers, opp["id"], sap["id"], body)

    assert response.status_code == 422, response.text
    assert_problem(response.json(), 422, "validation_error")
    if detail is not None:
        assert response.json()["detail"] == detail
    assert _line(client, headers, opp["id"], "SAP order interface") == sap
    assert edited_events(sync_engine, opp["id"]) == []


def test_a_300_character_reason_and_2000_hours_are_accepted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")

    body = {"effort_hours": 2000, "reason": "é" * 300}
    response = _edit(client, headers, opp["id"], sap["id"], body)

    assert response.status_code == 200, response.text
    line = _lines(response.json()["version"])["SAP order interface"]
    assert (line["effort_hours"], line["edit_reason"]) == (2000.0, "é" * 300)


def test_unchanged_values_are_a_no_op(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")

    same = {
        "effort_hours": 40.04,  # rounds to the stored 40.0
        "role_mix": {"engineer": 60, "project_manager": 20, "qa": 20},
        "reason": REASON,
    }
    response = _edit(client, headers, opp["id"], sap["id"], same)

    assert response.status_code == 200, response.text
    assert _lines(response.json()["version"])["SAP order interface"] == sap
    assert edited_events(sync_engine, opp["id"]) == []


def test_a_stale_or_missing_if_match_is_refused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, colleague_id).status_code == 200
    sap = _line(client, headers, opp["id"], "SAP order interface")
    first = _edit(client, headers, opp["id"], sap["id"], {"effort_hours": 32, "reason": REASON})
    assert first.status_code == 200

    stale = _edit(client, colleague, opp["id"], sap["id"], {"effort_hours": 20, "reason": "No"})
    missing = _edit(
        client, colleague, opp["id"], sap["id"], {"effort_hours": 20, "reason": "No"}, None
    )
    stale_no_op = _edit(
        client, colleague, opp["id"], sap["id"], {"effort_hours": 32, "reason": "No"}
    )

    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert stale.json()["detail"] == "Changed by Owner Person since you opened it."
    assert_problem(missing.json(), 428, "if_match_required")
    assert_problem(stale_no_op.json(), 412, "row_version_mismatch")
    line = _line(client, headers, opp["id"], "SAP order interface")
    assert (line["effort_hours"], line["row_version"], line["edit_reason"]) == (32.0, 2, REASON)
    assert len(edited_events(sync_engine, opp["id"])) == 1

    # A never-edited line names nobody.
    ops = _line(client, headers, opp["id"], "24/7 operations")
    unnamed = _edit(client, colleague, opp["id"], ops["id"], {"effort_hours": 1, "reason": "x"}, 5)
    assert unnamed.json()["detail"] == "Changed by someone else since you opened it."


def test_a_line_of_a_superseded_version_is_409(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")
    redraft(client, headers, opp["id"], db_url, gateway)

    response = _edit(client, headers, opp["id"], sap["id"], {"effort_hours": 32, "reason": REASON})

    assert_problem(response.json(), 409, "estimate_version_not_draft")
    assert response.json()["detail"] == (
        "This Estimate Version was replaced by a newer draft. Reload to see it."
    )
    first, _ = versions(sync_engine, opp["id"])
    (stored,) = [r for r in line_rows(sync_engine, first["id"]) if str(r["id"]) == sap["id"]]
    assert (stored["effort_hours"], stored["row_version"]) == (40, 1)


def test_who_may_edit(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    added = _add(client, headers, current, rep_id)
    assert added.status_code == 200
    assert _add(client, headers, added.json(), colleague_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    sap = _line(client, headers, opp["id"], "SAP order interface")
    body = {"effort_hours": 32, "reason": REASON}

    assert _estimate(client, rep, opp["id"])["can_edit_lines"] is False
    assert _estimate(client, reader, opp["id"])["can_edit_lines"] is False
    assert _estimate(client, colleague, opp["id"])["can_edit_lines"] is True
    for forbidden in (rep, reader):
        assert_problem(
            _edit(client, forbidden, opp["id"], sap["id"], body).json(), 403, "forbidden"
        )
    assert_problem(_edit(client, outsider, opp["id"], sap["id"], body).json(), 404, "not_found")
    unknown = "01a10891-875d-7f80-9921-65c3fbf28ecb"
    assert_problem(_edit(client, headers, opp["id"], unknown, body).json(), 404, "not_found")
    assert _edit(client, headers, opp["id"], "nope", body).status_code == 422
    assert (
        client.patch(f"{BASE}/{opp['id']}/estimate-lines/{sap['id']}", json=body).status_code == 401
    )
    assert edited_events(sync_engine, opp["id"]) == []

    # A line of another Opportunity is not found through this one.
    other_headers, other = drafted(client, sync_engine, db_url, gateway)
    assert other_headers  # the other Opportunity's owner
    assert_problem(_edit(client, headers, other["id"], sap["id"], body).json(), 404, "not_found")

    edited = _edit(client, colleague, opp["id"], sap["id"], body)
    assert edited.status_code == 200, edited.text
    assert _lines(edited.json()["version"])["SAP order interface"]["edited_by_name"] == "Colleague"


def test_a_linked_contingency_adds_to_the_edited_effort(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = assumption_tests.proposed(client, sync_engine, db_url, gateway)
    ops = _line(client, headers, opp["id"], "24/7 operations")
    assert (ops["effort_hours"], ops["contingency_hours"], ops["total_hours"]) == (16.0, 8.0, 24.0)

    response = _edit(client, headers, opp["id"], ops["id"], {"effort_hours": 20, "reason": REASON})

    assert response.status_code == 200, response.text
    version = response.json()["version"]
    line = _lines(version)["24/7 operations"]
    assert (line["effort_hours"], line["contingency_hours"], line["total_hours"]) == (
        20.0,
        8.0,
        28.0,
    )
    assert version["totals"]["contingency_hours"] == 20.0  # 8 on the line + 12 unallocated
    assert version["totals"]["total_hours"] == 128.5 + 4.0


# --- carrying edits to a re-draft -----------------------------------------------------------


def test_a_redraft_carries_an_edit_onto_the_matching_line(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")
    mix = {"engineer": 50, "project_manager": 30, "qa": 20}
    edited = _edit(
        client,
        headers,
        opp["id"],
        sap["id"],
        {"effort_hours": 32, "role_mix": mix, "reason": REASON},
    )
    v1_line = _lines(edited.json()["version"])["SAP order interface"]
    renamed = tuple(
        est_line("  sap ORDER interface ", ["R1"], effort=40.0)
        if line["title"] == "SAP order interface"
        else line
        for line in SIX
    )

    redraft(client, headers, opp["id"], db_url, gateway, renamed)

    version = _estimate(client, headers, opp["id"])["version"]
    assert version["version"] == 2
    line = _lines(version)["sap ORDER interface"]
    assert line["id"] != sap["id"]
    assert (line["effort_hours"], line["role_mix"]) == (32.0, mix)
    assert line["role_hours"] == {"engineer": 16.0, "project_manager": 9.6, "qa": 6.4}
    assert (line["edited"], line["edited_by_name"], line["edit_reason"]) == (
        True,
        "Owner Person",
        REASON,
    )
    assert line["edited_at"] == v1_line["edited_at"]
    assert (line["edit_carried_from_version"], line["row_version"]) == (1, 1)
    assert version["totals"]["effort_hours"] == 100.5
    assert (version["uncarried_edit_count"], version["uncarried_edits_from_version"]) == (0, None)
    others = [v for t, v in _lines(version).items() if t != "sap ORDER interface"]
    assert not any(v["edited"] for v in others)
    created = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = 'estimates.estimate_version.created' ORDER BY occurred_at, id",
        o=opp["id"],
    )
    assert [
        (e["payload"]["carried_edit_count"], e["payload"]["uncarried_edit_count"]) for e in created
    ] == [
        (0, 0),
        (1, 0),
    ]
    assert REASON not in str(created)

    # The carried line is editable at row version 1; editing it makes it a direct edit.
    again = _edit(client, headers, opp["id"], line["id"], {"effort_hours": 30, "reason": "Less"})
    assert again.status_code == 200, again.text
    after = _lines(again.json()["version"])["sap ORDER interface"]
    assert (after["edit_carried_from_version"], after["edit_reason"], after["row_version"]) == (
        None,
        "Less",
        2,
    )
    (_, event) = edited_events(sync_engine, opp["id"])
    assert (event["payload"]["version"], event["payload"]["before_hours"]) == (2, 32.0)

    # A second re-draft carries it again, from v2.
    redraft(client, headers, opp["id"], db_url, gateway, renamed)
    third = _lines(_estimate(client, headers, opp["id"])["version"])["sap ORDER interface"]
    assert (third["effort_hours"], third["edit_carried_from_version"]) == (30.0, 2)


@pytest.mark.parametrize(
    "replacement",
    [
        (),  # gone
        (est_line("SAP order interface", ["R1"], section="data", effort=40.0),),  # other section
        (  # two matches
            est_line("SAP order interface", ["R1"], effort=40.0),
            est_line("sap order interface", ["R1"], effort=8.0),
        ),
    ],
    ids=["gone", "other-section", "two"],
)
def test_an_edit_without_one_matching_line_is_counted_and_stays_in_the_old_version(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    replacement: tuple[dict[str, Any], ...],
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")
    ops = _line(client, headers, opp["id"], "24/7 operations")
    assert (
        _edit(
            client, headers, opp["id"], sap["id"], {"effort_hours": 32, "reason": REASON}
        ).status_code
        == 200
    )
    assert (
        _edit(
            client, headers, opp["id"], ops["id"], {"effort_hours": 10, "reason": "Fewer shifts"}
        ).status_code
        == 200
    )
    lines = tuple(line for line in SIX if line["title"] != "SAP order interface") + replacement

    redraft(client, headers, opp["id"], db_url, gateway, lines)

    version = _estimate(client, headers, opp["id"])["version"]
    assert (version["uncarried_edit_count"], version["uncarried_edits_from_version"]) == (1, 1)
    current = _lines(version)
    assert current["24/7 operations"]["effort_hours"] == 10.0  # the other edit is carried
    assert all(
        not line["edited"] and line["effort_hours"] in (40.0, 8.0)
        for title, line in current.items()
        if title.casefold() == "sap order interface"
    )
    first, second = versions(sync_engine, opp["id"])
    assert second["uncarried_edit_count"] == 1
    (kept,) = [r for r in line_rows(sync_engine, first["id"]) if str(r["id"]) == sap["id"]]
    assert (kept["effort_hours"], kept["edit_reason"]) == (32, REASON)
    created = rows(
        sync_engine,
        "SELECT payload FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = 'estimates.estimate_version.created' ORDER BY occurred_at, id",
        o=opp["id"],
    )
    assert (
        created[1]["payload"]["carried_edit_count"],
        created[1]["payload"]["uncarried_edit_count"],
    ) == (1, 1)


def _created_counts(engine: Engine, opp_id: str) -> list[tuple[int, int]]:
    created = rows(
        engine,
        "SELECT payload FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = 'estimates.estimate_version.created' ORDER BY occurred_at, id",
        o=opp_id,
    )
    return [
        (e["payload"]["carried_edit_count"], e["payload"]["uncarried_edit_count"]) for e in created
    ]


def test_an_edit_carries_down_a_chain_of_redrafts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    sap = _line(client, headers, opp["id"], "SAP order interface")
    mix = {"engineer": 50, "project_manager": 30, "qa": 20}
    body = {"effort_hours": 32, "role_mix": mix, "reason": REASON}
    assert _edit(client, headers, opp["id"], sap["id"], body).status_code == 200

    redraft(client, headers, opp["id"], db_url, gateway)  # v2: carried from v1, not edited
    redraft(client, headers, opp["id"], db_url, gateway)  # v3

    version = _estimate(client, headers, opp["id"])["version"]
    assert version["version"] == 3
    line = _lines(version)["SAP order interface"]
    assert (line["effort_hours"], line["role_mix"], line["edit_reason"]) == (32.0, mix, REASON)
    assert (line["edited_by_name"], line["edit_carried_from_version"]) == ("Owner Person", 2)
    assert version["uncarried_edit_count"] == 0
    assert _created_counts(sync_engine, opp["id"]) == [(0, 0), (1, 0), (1, 0)]
    assert len(edited_events(sync_engine, opp["id"])) == 1  # carrying is not an edit


def test_two_edits_matching_one_new_line_carry_once(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    twin = est_line(" sap ORDER  interface ", ["R1"], effort=8.0)
    twin["title"] = " sap ORDER interface "  # same section, differs by case and spaces only
    gateway.replies = [lines_out(*SIX, twin)]
    assert drain(db_url, DRAFT) == ["succeeded"]
    v1 = _lines(_estimate(client, headers, opp["id"])["version"])
    first, second = v1["SAP order interface"], v1["sap ORDER interface"]
    for line, hours, reason in ((first, 32, "First"), (second, 4, "Second")):
        body = {"effort_hours": hours, "reason": reason}
        assert _edit(client, headers, opp["id"], line["id"], body).status_code == 200

    redraft(client, headers, opp["id"], db_url, gateway)  # one SAP line in v2

    version = _estimate(client, headers, opp["id"])["version"]
    line = _lines(version)["SAP order interface"]
    assert (line["effort_hours"], line["edit_reason"], line["edit_carried_from_version"]) == (
        32.0,
        "First",
        1,
    )
    assert (version["uncarried_edit_count"], version["uncarried_edits_from_version"]) == (1, 1)
    assert _created_counts(sync_engine, opp["id"]) == [(0, 0), (1, 1)]


def test_a_redraft_without_edits_carries_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)

    redraft(client, headers, opp["id"], db_url, gateway)

    version = _estimate(client, headers, opp["id"])["version"]
    assert version["uncarried_edit_count"] == 0
    assert not any(line["edited"] for line in _lines(version).values())


# --- grants ---------------------------------------------------------------------------------


def test_psa_app_may_update_only_the_edit_columns_of_a_line(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = drafted(client, sync_engine, db_url, gateway)
    (version,) = versions(sync_engine, opp["id"])
    row = line_rows(sync_engine, version["id"])[0]

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE estimates_estimate_lines SET effort_hours = effort_hours, "
                "role_mix = role_mix, row_version = row_version, edited_by = edited_by, "
                "edited_at = edited_at, edit_reason = edit_reason, "
                "edit_carried_from_version = edit_carried_from_version WHERE id = :i"
            ),
            {"i": row["id"]},
        )
    for column in ("title", "section", "basis", "position", "version_id"):
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(
                sa.text(f"UPDATE estimates_estimate_lines SET {column} = {column} WHERE id = :i"),
                {"i": row["id"]},
            )
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM estimates_estimate_lines WHERE id = :i"), {"i": row["id"]}
        )
