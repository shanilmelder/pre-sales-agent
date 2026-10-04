"""Editing and confirming Requirements (Story 2.6): `PATCH …/requirements/{id}`,
`POST …/requirements/{id}/confirm` and `POST …/requirements/confirm-all`, against a real,
migrated Postgres as psa_app, with the fake ModelGateway of `test_intake_extraction.py`."""

from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.intake.domain.requirements import REQUIREMENT_TEXT_MAX, requirement_text
from tests import test_intake_extraction as extraction_tests
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, EXTRACT, FakeGateway, drain, out, parsed
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import PSE, _add, _if_match, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

NOTE = (
    "We must connect to SAP. The site runs 24/7. Peak is 900 orders per hour. "
    "Single sign-on is required. Pricing in EUR. "
)
ITEMS = (
    ("Connect to SAP.", "integration", [("S1", "We must connect to SAP")]),
    ("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]),
    ("Peak 900 orders/hour.", "functional", [("S1", "Peak is 900 orders per hour")]),
    ("Single sign-on.", "security", [("S1", "Single sign-on is required")]),
    ("Prices in EUR.", "commercial", [("S1", "Pricing in EUR")]),
)


# --- helpers --------------------------------------------------------------------------------


def _extracted(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, count: int = 2
) -> tuple[dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    """An Opportunity with `count` extracted Requirements (in `ITEMS` order)."""
    headers, opp, _ = parsed(client, engine, db_url, ("n.txt", f"{NOTE}{uuid4()}"))
    gateway.replies = [out(*ITEMS[:count])]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    return headers, opp, _list(client, headers, opp["id"])


def _list(client: TestClient, headers: dict[str, str], opp_id: str) -> list[dict[str, Any]]:
    response = client.get(f"{BASE}/{opp_id}/requirements", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _patch(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    body: dict[str, Any],
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.patch(
        f"{BASE}/{opp_id}/requirements/{item['id']}", headers={**headers, **extra}, json=body
    )


def _confirm(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.post(
        f"{BASE}/{opp_id}/requirements/{item['id']}/confirm", headers={**headers, **extra}
    )


def _confirm_all(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/requirements/confirm-all", headers=headers)


def _row(engine: Engine, requirement_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                sa.text("SELECT * FROM intake_requirements WHERE id = :i"), {"i": requirement_id}
            )
            .mappings()
            .one()
        )


def _history(engine: Engine, requirement_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM intake_requirement_versions WHERE requirement_id = :i "
                    "ORDER BY version"
                ),
                {"i": requirement_id},
            ).mappings()
        ]


def _events(engine: Engine, requirement_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT event_type, actor_type, actor_id, subject_version, payload, "
                    "opportunity_id FROM platform_trace_events "
                    "WHERE subject_type = 'intake.requirement' AND subject_id = :i "
                    "ORDER BY occurred_at, id"
                ),
                {"i": requirement_id},
            ).mappings()
        ]


# --- domain ---------------------------------------------------------------------------------


def test_requirement_text_is_trimmed_and_bounded_in_code_points() -> None:
    assert requirement_text("  Needs SSO.\n") == "Needs SSO."
    assert requirement_text("😀" * REQUIREMENT_TEXT_MAX) == "😀" * REQUIREMENT_TEXT_MAX
    for bad in ("", "   \n\t", "x" * (REQUIREMENT_TEXT_MAX + 1)):
        with pytest.raises(ValueError):
            requirement_text(bad)


# --- history --------------------------------------------------------------------------------


def test_extraction_writes_version_1_history(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, _, (sap, _) = _extracted(client, sync_engine, db_url, gateway)

    (v1,) = _history(sync_engine, sap["id"])
    assert (v1["version"], v1["text"], v1["classification"]) == (
        1,
        "Connect to SAP.",
        "integration",
    )
    assert v1["created_by"].startswith("intake_agent@")
    assert (sap["confirmed_at"], sap["confirmed_by"], sap["last_changed_by"]) == (None, None, None)


def test_versions_are_immutable_for_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, _, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE intake_requirement_versions SET text = 'x' WHERE requirement_id = :i"),
            {"i": sap["id"]},
        )
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM intake_requirement_versions WHERE requirement_id = :i"),
            {"i": sap["id"]},
        )


# --- edit -----------------------------------------------------------------------------------


def test_editing_the_text_makes_version_2_locked_and_human(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    evidence = sap["evidence"]

    response = _patch(
        client, headers, opp["id"], sap, {"text": "  Connect to SAP S/4HANA.  "}, sap["row_version"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert response.headers["ETag"] == f'"{body["row_version"]}"'
    assert body["text"] == "Connect to SAP S/4HANA."
    assert (body["version"], body["origin"], body["locked_by_human"]) == (2, "human", True)
    assert body["row_version"] == sap["row_version"] + 1
    assert body["classification"] == "integration"
    assert body["evidence"] == evidence
    assert body["last_changed_by"]["name"] == "Owner Person"
    assert [(h["version"], h["text"]) for h in _history(sync_engine, sap["id"])] == [
        (1, "Connect to SAP."),
        (2, "Connect to SAP S/4HANA."),
    ]
    (event,) = _events(sync_engine, sap["id"])
    assert event["event_type"] == "intake.requirement.edited"
    assert event["payload"] == {"fields": ["text"], "version": 2}
    assert event["subject_version"] == 2
    assert str(event["opportunity_id"]) == opp["id"]
    assert "SAP" not in str(event["payload"])
    assert _list(client, headers, opp["id"])[0] == body


def test_editing_the_classification_only(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (_, uptime) = _extracted(client, sync_engine, db_url, gateway)

    response = _patch(
        client, headers, opp["id"], uptime, {"classification": "security"}, uptime["row_version"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["classification"], body["text"], body["version"]) == ("security", "Runs 24/7.", 2)
    assert (body["origin"], body["locked_by_human"]) == ("human", True)
    history = _history(sync_engine, uptime["id"])
    assert [(h["version"], h["classification"]) for h in history] == [
        (1, "non_functional"),
        (2, "security"),
    ]
    (event,) = _events(sync_engine, uptime["id"])
    assert event["payload"] == {"fields": ["classification"], "version": 2}


def test_editing_both_names_both_fields(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)

    response = _patch(
        client,
        headers,
        opp["id"],
        sap,
        {"text": "SAP via IDoc.", "classification": "data"},
        sap["row_version"],
    )

    assert response.status_code == 200, response.text
    (event,) = _events(sync_engine, sap["id"])
    assert event["payload"] == {"fields": ["text", "classification"], "version": 2}


@pytest.mark.parametrize(
    "body",
    [
        {"text": "Connect to SAP."},
        {"text": "  Connect to SAP.\n"},
        {"classification": "integration"},
        {"text": "Connect to SAP.", "classification": "integration"},
        {},
    ],
)
def test_a_no_op_edit_writes_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    body: dict[str, Any],
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    before = _row(sync_engine, sap["id"])

    response = _patch(client, headers, opp["id"], sap, body, sap["row_version"])

    assert response.status_code == 200, response.text
    assert response.json() == sap
    assert _row(sync_engine, sap["id"]) == before
    assert len(_history(sync_engine, sap["id"])) == 1
    assert _events(sync_engine, sap["id"]) == []


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "   \n"},
        {"text": "x" * (REQUIREMENT_TEXT_MAX + 1)},
        {"classification": "nice_to_have"},
        {"text": 12},
        {"text": "Fine.", "status": "superseded"},
    ],
)
def test_invalid_edits_are_422_and_write_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    body: dict[str, Any],
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    before = _row(sync_engine, sap["id"])

    response = _patch(client, headers, opp["id"], sap, body, sap["row_version"])

    assert response.status_code == 422, response.text
    assert_problem(response.json(), 422, "validation_error")
    assert _row(sync_engine, sap["id"]) == before
    assert _events(sync_engine, sap["id"]) == []


def test_text_errors_carry_the_sentence_to_show(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)

    blank = _patch(client, headers, opp["id"], sap, {"text": " "}, sap["row_version"])
    long = _patch(client, headers, opp["id"], sap, {"text": "x" * 2001}, sap["row_version"])

    assert blank.json()["detail"] == "The Requirement text can't be blank."
    assert long.json()["detail"] == "The Requirement text can be at most 2,000 characters."


def test_a_stale_if_match_is_412_and_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    assert _patch(
        client, headers, opp["id"], sap, {"text": "First."}, sap["row_version"]
    ).is_success
    before = _row(sync_engine, sap["id"])

    stale = _patch(client, headers, opp["id"], sap, {"text": "Second."}, sap["row_version"])
    stale_no_op = _patch(client, headers, opp["id"], sap, {"text": "First."}, sap["row_version"])
    stale_confirm = _confirm(client, headers, opp["id"], sap, sap["row_version"])

    for response in (stale, stale_no_op, stale_confirm):
        assert response.status_code == 412, response.text
        assert_problem(response.json(), 412, "row_version_mismatch")
    assert _row(sync_engine, sap["id"]) == before
    assert len(_history(sync_engine, sap["id"])) == 2
    assert len(_events(sync_engine, sap["id"])) == 1


def test_a_missing_if_match_is_428(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)

    edit = _patch(client, headers, opp["id"], sap, {"text": "New."})
    confirm = _confirm(client, headers, opp["id"], sap)

    for response in (edit, confirm):
        assert response.status_code == 428, response.text
        assert_problem(response.json(), 428, "if_match_required")
    assert _row(sync_engine, sap["id"])["version"] == 1
    assert _events(sync_engine, sap["id"]) == []


def test_a_requirement_of_another_opportunity_or_superseded_is_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    _, _, (theirs, _) = _extracted(client, sync_engine, db_url, gateway)

    wrong_opp = _patch(client, headers, opp["id"], theirs, {"text": "X."}, theirs["row_version"])
    unknown = _patch(client, headers, opp["id"], {"id": str(uuid4())}, {"text": "X."}, 1)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE intake_requirements SET status = 'superseded' WHERE id = :i"),
            {"i": sap["id"]},
        )
    superseded = _confirm(client, headers, opp["id"], sap, sap["row_version"])

    for response in (wrong_opp, unknown, superseded):
        assert response.status_code == 404, response.text
        assert_problem(response.json(), 404, "not_found")
    assert _row(sync_engine, theirs["id"])["version"] == 1


# --- who ------------------------------------------------------------------------------------


def test_a_sales_rep_collaborator_is_403_and_sees_no_edit_rights(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200

    edit = _patch(client, rep, opp["id"], sap, {"text": "X."}, sap["row_version"])
    confirm = _confirm(client, rep, opp["id"], sap, sap["row_version"])
    confirm_all = _confirm_all(client, rep, opp["id"])
    listed = client.get(f"{BASE}/{opp['id']}/requirements", headers=rep).json()

    for response in (edit, confirm, confirm_all):
        assert response.status_code == 403, response.text
        assert_problem(response.json(), 403, "forbidden")
    assert listed["can_edit_requirements"] is False
    assert listed["can_start_extraction"] is True
    assert _events(sync_engine, sap["id"]) == []


def test_a_presales_collaborator_may_edit(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    pse, pse_id = _user(client, sync_engine, "Colleague Person", PSE)
    assert _add(client, headers, opp, pse_id).status_code == 200

    response = _patch(client, pse, opp["id"], sap, {"text": "Edited."}, sap["row_version"])

    assert response.status_code == 200, response.text
    assert response.json()["last_changed_by"] == {"id": str(pse_id), "name": "Colleague Person"}
    assert client.get(f"{BASE}/{opp['id']}/requirements", headers=pse).json()[
        "can_edit_requirements"
    ]


def test_a_reader_is_403_and_an_outsider_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    for headers, status, code in ((reader, 403, "forbidden"), (outsider, 404, "not_found")):
        edit = _patch(client, headers, opp["id"], sap, {"text": "X."}, sap["row_version"])
        confirm = _confirm(client, headers, opp["id"], sap, sap["row_version"])
        confirm_all = _confirm_all(client, headers, opp["id"])
        for response in (edit, confirm, confirm_all):
            assert response.status_code == status, response.text
            assert_problem(response.json(), status, code)
    assert _row(sync_engine, sap["id"])["confirmed_at"] is None


# --- confirm --------------------------------------------------------------------------------


def test_confirming_sets_confirmed_and_locks_without_a_new_version(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)

    response = _confirm(client, headers, opp["id"], sap, sap["row_version"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert response.headers["ETag"] == f'"{body["row_version"]}"'
    assert body["confirmed_at"] is not None
    assert body["confirmed_by"]["name"] == "Owner Person"
    assert body["last_changed_by"] == body["confirmed_by"]
    assert (body["locked_by_human"], body["version"], body["origin"]) == (True, 1, "extracted")
    assert body["row_version"] == sap["row_version"] + 1
    assert body["text"] == sap["text"]
    assert len(_history(sync_engine, sap["id"])) == 1
    (event,) = _events(sync_engine, sap["id"])
    assert (event["event_type"], event["payload"]) == (
        "intake.requirement.confirmed",
        {"version": 1},
    )


def test_confirming_again_is_200_with_no_new_event(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    first = _confirm(client, headers, opp["id"], sap, sap["row_version"]).json()
    before = _row(sync_engine, sap["id"])

    again = _confirm(client, headers, opp["id"], sap, first["row_version"])
    # Idempotent: even from a view read before the first confirmation.
    from_old_view = _confirm(client, headers, opp["id"], sap, sap["row_version"])

    for response in (again, from_old_view):
        assert response.status_code == 200, response.text
        assert response.json() == first
    assert _row(sync_engine, sap["id"]) == before
    assert len(_events(sync_engine, sap["id"])) == 1


def test_an_edit_after_confirming_keeps_it_confirmed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    confirmed = _confirm(client, headers, opp["id"], sap, sap["row_version"]).json()

    edited = _patch(
        client, headers, opp["id"], sap, {"text": "Edited."}, confirmed["row_version"]
    ).json()

    assert edited["confirmed_at"] == confirmed["confirmed_at"]
    assert (edited["version"], edited["origin"]) == (2, "human")


def test_confirm_all_confirms_only_the_unconfirmed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, items = _extracted(client, sync_engine, db_url, gateway, count=5)
    for item in items[:2]:
        assert _confirm(client, headers, opp["id"], item, item["row_version"]).is_success

    response = _confirm_all(client, headers, opp["id"])

    assert response.status_code == 200, response.text
    assert response.json() == {"count": 3}
    after = _list(client, headers, opp["id"])
    assert all(i["confirmed_at"] and i["locked_by_human"] for i in after)
    for item in items:
        assert len(_events(sync_engine, item["id"])) == 1
    assert _confirm_all(client, headers, opp["id"]).json() == {"count": 0}
    for item in items:
        assert len(_events(sync_engine, item["id"])) == 1


# --- locking survives re-extraction ---------------------------------------------------------


def test_edited_and_confirmed_requirements_survive_a_rerun(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, uptime, peak) = _extracted(client, sync_engine, db_url, gateway, count=3)
    edited = _patch(
        client, headers, opp["id"], sap, {"text": "Connect to SAP S/4."}, sap["row_version"]
    ).json()
    confirmed = _confirm(client, headers, opp["id"], uptime, uptime["row_version"]).json()

    started = client.post(f"{BASE}/{opp['id']}/extractions", headers=headers)
    assert started.status_code == 201, started.text
    gateway.replies = [out(ITEMS[3])]
    assert drain(db_url, EXTRACT) == ["succeeded"]

    after = {item["id"]: item for item in _list(client, headers, opp["id"])}
    assert after[sap["id"]] == edited
    assert after[uptime["id"]] == confirmed
    assert peak["id"] not in after
    assert _row(sync_engine, peak["id"])["status"] == "superseded"
    assert [i["text"] for i in after.values()] == [
        "Connect to SAP S/4.",
        "Runs 24/7.",
        "Single sign-on.",
    ]


def test_demo_flow_fix_one_confirm_all_and_rerun(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, items = _extracted(client, sync_engine, db_url, gateway, count=3)
    first = items[0]
    assert _patch(
        client, headers, opp["id"], first, {"text": "Fixed wording."}, first["row_version"]
    ).is_success
    assert _confirm_all(client, headers, opp["id"]).json() == {"count": 3}
    confirmed = _list(client, headers, opp["id"])

    assert client.post(f"{BASE}/{opp['id']}/extractions", headers=headers).status_code == 201
    gateway.replies = [out(*ITEMS)]
    assert drain(db_url, EXTRACT) == ["succeeded"]

    after = _list(client, headers, opp["id"])
    assert after[:3] == confirmed
    assert all(i["confirmed_at"] for i in confirmed)


def test_uuid_actor_ids_in_history_name_the_user(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    assert _patch(client, headers, opp["id"], sap, {"text": "New."}, sap["row_version"]).is_success

    v2 = _history(sync_engine, sap["id"])[1]
    assert UUID(v2["created_by"])


# --- who changed it last --------------------------------------------------------------------


@pytest.mark.parametrize("editor_last", [True, False])
def test_last_changed_by_names_whoever_changed_it_last(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    editor_last: bool,
) -> None:
    owner, opp, (sap, _) = _extracted(client, sync_engine, db_url, gateway)
    colleague, colleague_id = _user(client, sync_engine, "Colleague Person", PSE)
    assert _add(client, owner, opp, colleague_id).status_code == 200
    # Owner confirms then the colleague edits, or the colleague edits then the owner confirms.
    if editor_last:
        first = _confirm(client, owner, opp["id"], sap, sap["row_version"])
        last = _patch(
            client, colleague, opp["id"], sap, {"text": "Edited."}, first.json()["row_version"]
        )
        expected = {"id": str(colleague_id), "name": "Colleague Person"}
    else:
        first = _patch(client, colleague, opp["id"], sap, {"text": "Edited."}, sap["row_version"])
        last = _confirm(client, owner, opp["id"], sap, first.json()["row_version"])
        expected = {"id": last.json()["confirmed_by"]["id"], "name": "Owner Person"}
    assert first.status_code == 200, first.text
    assert last.status_code == 200, last.text

    assert last.json()["last_changed_by"] == expected
    (listed,) = [i for i in _list(client, owner, opp["id"]) if i["id"] == sap["id"]]
    assert listed["last_changed_by"] == expected
    assert listed["confirmed_by"]["name"] == "Owner Person"


# --- migration 0010 backfill ----------------------------------------------------------------


def test_migration_backfills_version_1_for_existing_requirements(sync_engine: Engine) -> None:
    opportunity_id = uuid4()
    traced, untraced = uuid4(), uuid4()
    traced_extraction, untraced_extraction = uuid4(), uuid4()
    _alembic("downgrade", "0009_intake_requirements")
    try:
        with sync_engine.begin() as conn:
            for extraction_id in (traced_extraction, untraced_extraction):
                conn.execute(
                    sa.text(
                        "INSERT INTO intake_extractions (id, opportunity_id, status) "
                        "VALUES (:e, :o, 'succeeded')"
                    ),
                    {"e": extraction_id, "o": opportunity_id},
                )
            for requirement_id, extraction_id, text, classification in (
                (traced, traced_extraction, "Traced one.", "security"),
                (untraced, untraced_extraction, "Untraced one.", "data"),
            ):
                conn.execute(
                    sa.text(
                        "INSERT INTO intake_requirements (id, opportunity_id, text, "
                        "classification, origin, locked_by_human, status, version, "
                        "extraction_id, row_version) VALUES (:i, :o, :t, :c, 'extracted', "
                        "false, 'active', 1, :e, 1)"
                    ),
                    {
                        "i": requirement_id,
                        "o": opportunity_id,
                        "t": text,
                        "c": classification,
                        "e": extraction_id,
                    },
                )
            conn.execute(
                sa.text(
                    "INSERT INTO platform_trace_events (id, opportunity_id, actor_type, actor_id, "
                    "event_type, subject_type, subject_id, payload) VALUES (:id, :o, 'agent', "
                    "'intake_agent@9.9.9', 'intake.extraction.completed', 'intake.extraction', "
                    ":e, '{}'::jsonb)"
                ),
                {"id": uuid4(), "o": opportunity_id, "e": traced_extraction},
            )
    finally:
        _alembic("upgrade", "head")

    (traced_v1,) = _history(sync_engine, str(traced))
    (untraced_v1,) = _history(sync_engine, str(untraced))
    assert (
        traced_v1["version"],
        traced_v1["text"],
        traced_v1["classification"],
        traced_v1["created_by"],
    ) == (1, "Traced one.", "security", "intake_agent@9.9.9")
    assert (
        untraced_v1["version"],
        untraced_v1["text"],
        untraced_v1["classification"],
        untraced_v1["created_by"],
    ) == (1, "Untraced one.", "data", "intake_agent")
