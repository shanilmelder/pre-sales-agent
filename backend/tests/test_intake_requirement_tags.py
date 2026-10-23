"""Requirement Integration Type tags (Story 4.1): `PUT …/requirements/{id}/integration-types`
against a real, migrated Postgres as psa_app, with the fake ModelGateway of
`test_intake_extraction.py`: tag, an unchanged set, stale and missing `If-Match`, sales
representatives, retired and wrong-kind entries, re-extraction leaving tags alone, split and
merge inheritance, a classification change keeping them, and the list's untagged count."""

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_intake_extraction as extraction_tests
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, FakeGateway
from tests.test_intake_incremental import SAP, SAP_S4, UPTIME, _first_run, _new_source
from tests.test_intake_requirement_edits import _events, _list, _patch, _row
from tests.test_intake_requirement_lifecycle import TWO_PARTS, _create, _merge, _split
from tests.test_knowledge_checklists import _entry, _retire_entry
from tests.test_opportunities import _add, _if_match, _user
from tests.test_role_admin import _admin

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

TAGGED = "intake.requirement.integration_types_tagged"


def _tag(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    item: dict[str, Any],
    ids: list[str],
    version: int | None = None,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.put(
        f"{BASE}/{opp_id}/requirements/{item['id']}/integration-types",
        headers={**headers, **extra},
        json={"integration_type_ids": ids},
    )


def _tagged(
    client: TestClient, headers: dict[str, str], opp_id: str, item: dict[str, Any], ids: list[str]
) -> dict[str, Any]:
    response = _tag(client, headers, opp_id, item, ids, item["row_version"])
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _tag_rows(engine: Engine, requirement_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM intake_requirement_integration_types "
                    "WHERE requirement_id = :r ORDER BY tagged_at, entry_id"
                ),
                {"r": requirement_id},
            ).mappings()
        ]


def _tag_events(engine: Engine, requirement_id: str) -> list[dict[str, Any]]:
    return [e for e in _events(engine, requirement_id) if e["event_type"] == TAGGED]


def _ids(item: dict[str, Any]) -> list[str]:
    return [t["id"] for t in item["integration_types"]]


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    headers, _ = _admin(client)
    return headers


# --- tag ------------------------------------------------------------------------------------


def test_tagging_bumps_the_row_version_and_traces_the_change(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    sap_type = _entry(client, admin)

    response = _tag(client, headers, opp["id"], sap, [sap_type], sap["row_version"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert response.headers["ETag"] == f'"{body["row_version"]}"'
    assert body["row_version"] == sap["row_version"] + 1
    assert body["version"] == sap["version"]  # tags are not versioned
    (tag,) = body["integration_types"]
    assert tag["id"] == sap_type and tag["retired"] is False
    assert tag["code"].startswith("C-") and tag["name"].startswith("Entry ")
    (row,) = _tag_rows(sync_engine, sap["id"])
    assert str(row["entry_id"]) == sap_type and row["tagged_by"] is not None
    (event,) = _tag_events(sync_engine, sap["id"])
    assert event["payload"] == {"added": [sap_type], "removed": []}
    assert event["actor_type"] == "user" and event["subject_version"] == sap["version"]
    assert str(event["opportunity_id"]) == opp["id"]
    # The list shows it too, and the tagged integration Requirement no longer counts.
    listed = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()
    assert _ids(listed["items"][0]) == [sap_type]
    assert listed["untagged_integration_count"] == 0


def test_replacing_the_set_records_added_and_removed(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    a, b, c = (_entry(client, admin) for _ in range(3))
    first = _tagged(client, headers, opp["id"], sap, [a, b, a])  # a repeat counts once
    assert _ids(first) == [a, b]

    second = _tagged(client, headers, opp["id"], first, [b, c])

    assert _ids(second) == [b, c]
    events = _tag_events(sync_engine, sap["id"])
    assert [e["payload"] for e in events] == [
        {"added": [a, b], "removed": []},
        {"added": [c], "removed": [a]},
    ]
    cleared = _tagged(client, headers, opp["id"], second, [])
    assert cleared["integration_types"] == []
    assert _tag_rows(sync_engine, sap["id"]) == []


def test_an_unchanged_set_writes_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    sap_type = _entry(client, admin)
    tagged = _tagged(client, headers, opp["id"], sap, [sap_type])

    again = _tag(client, headers, opp["id"], tagged, [sap_type], tagged["row_version"])
    stale_again = _tag(client, headers, opp["id"], tagged, [sap_type], sap["row_version"])

    assert again.status_code == 200, again.text
    assert again.json()["row_version"] == tagged["row_version"]
    assert len(_tag_events(sync_engine, sap["id"])) == 1
    assert stale_again.status_code == 412
    assert_problem(stale_again.json(), 412, "row_version_mismatch")


def test_a_stale_or_missing_if_match_changes_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    sap_type = _entry(client, admin)
    # Extraction refines the unlocked Requirement, bumping its row version.
    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME)
    assert _row(sync_engine, sap["id"])["row_version"] > sap["row_version"]

    stale = _tag(client, headers, opp["id"], sap, [sap_type], sap["row_version"])
    missing = _tag(client, headers, opp["id"], sap, [sap_type])

    assert stale.status_code == 412
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert missing.status_code == 428
    assert_problem(missing.json(), 428, "if_match_required")
    assert _tag_rows(sync_engine, sap["id"]) == []
    assert _tag_events(sync_engine, sap["id"]) == []


# --- validation -----------------------------------------------------------------------------


def test_retired_unknown_and_wrong_kind_entries_are_422(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    retired = _entry(client, admin)
    _retire_entry(client, admin, retired)
    work_package = _entry(client, admin, kind="work_package")

    for ids in ([retired], [work_package], [str(uuid4())]):
        response = _tag(client, headers, opp["id"], sap, ids, sap["row_version"])
        assert response.status_code == 422, response.text
        assert_problem(response.json(), 422, "validation_error")
        assert response.json()["detail"] == (
            "A retired or unknown Integration Type can't be chosen."
        )
    too_many = _tag(
        client, headers, opp["id"], sap, [str(uuid4()) for _ in range(51)], sap["row_version"]
    )
    assert too_many.status_code == 422
    assert_problem(too_many.json(), 422, "validation_error")
    assert _row(sync_engine, sap["id"])["row_version"] == sap["row_version"]
    assert _tag_rows(sync_engine, sap["id"]) == []


def test_a_stale_if_match_wins_over_a_retired_id(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    retired = _entry(client, admin)
    _retire_entry(client, admin, retired)

    stale = _tag(client, headers, opp["id"], sap, [retired], sap["row_version"] + 1)
    missing = _tag(client, headers, opp["id"], sap, [retired])

    assert stale.status_code == 412, stale.text
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert missing.status_code == 428, missing.text
    assert_problem(missing.json(), 428, "if_match_required")
    assert _tag_rows(sync_engine, sap["id"]) == []


def test_a_stored_tag_retired_later_stays_but_cannot_come_back(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    old, new = _entry(client, admin), _entry(client, admin)
    tagged = _tagged(client, headers, opp["id"], sap, [old])
    _retire_entry(client, admin, old)

    kept = _tagged(client, headers, opp["id"], tagged, [old, new])

    assert [(t["id"], t["retired"]) for t in kept["integration_types"]] == [
        (old, True),
        (new, False),
    ]
    removed = _tagged(client, headers, opp["id"], kept, [new])
    back = _tag(client, headers, opp["id"], removed, [new, old], removed["row_version"])
    assert back.status_code == 422
    assert_problem(back.json(), 422, "validation_error")


# --- who ------------------------------------------------------------------------------------


def test_a_sales_rep_is_403_and_sees_the_tags_read_only(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    sap_type = _entry(client, admin)
    tagged = _tagged(client, headers, opp["id"], sap, [sap_type])
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200

    response = _tag(client, rep, opp["id"], tagged, [], tagged["row_version"])
    listed = client.get(f"{BASE}/{opp['id']}/requirements", headers=rep).json()

    assert response.status_code == 403, response.text
    assert_problem(response.json(), 403, "forbidden")
    assert listed["can_edit_requirements"] is False
    assert _ids(listed["items"][0]) == [sap_type]


def test_an_outsider_gets_404(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    _, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    outsider, _ = _user(client, sync_engine, "Outsider Person", "presales_engineer")

    response = _tag(client, outsider, opp["id"], sap, [], sap["row_version"])

    assert response.status_code == 404
    assert_problem(response.json(), 404, "not_found")


# --- extraction, split, merge, classification ------------------------------------------------


def test_re_extraction_leaves_the_tags_alone(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    sap_type = _entry(client, admin)
    tagged = _tagged(client, headers, opp["id"], sap, [sap_type])
    assert tagged["locked_by_human"] is False  # tagging doesn't lock it

    _new_source(client, headers, opp, db_url, gateway, SAP_S4, UPTIME)

    refined = next(i for i in _list(client, headers, opp["id"]) if i["id"] == sap["id"])
    assert refined["version"] == 2 and refined["text"] == SAP_S4[0]
    assert _ids(refined) == [sap_type]
    assert len(_tag_events(sync_engine, sap["id"])) == 1


def test_split_children_inherit_and_a_merge_takes_the_union(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, uptime) = _first_run(client, sync_engine, db_url, gateway)
    a, b = _entry(client, admin), _entry(client, admin)
    sap = _tagged(client, headers, opp["id"], sap, [a])
    uptime = _tagged(client, headers, opp["id"], uptime, [a, b])

    split = _split(client, headers, opp["id"], sap, TWO_PARTS, sap["row_version"])

    assert split.status_code == 201, split.text
    first, second = split.json()["items"]
    assert _ids(first) == [a] and _ids(second) == [a]
    merged = _merge(
        client,
        headers,
        opp["id"],
        [(first["id"], first["row_version"]), (uptime["id"], uptime["row_version"])],
    )
    assert merged.status_code == 201, merged.text
    assert sorted(_ids(merged.json())) == sorted([a, b])


def test_a_classification_change_keeps_the_tags_and_the_untagged_count_follows(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    admin: dict[str, str],
) -> None:
    headers, opp, (sap, _) = _first_run(client, sync_engine, db_url, gateway)
    assert SAP[1] == "integration"
    _create(client, headers, opp["id"], "Exchange orders by EDI.", "integration")
    _create(client, headers, opp["id"], "Show a dashboard.", "functional")
    listed = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()
    assert listed["untagged_integration_count"] == 2
    sap_type = _entry(client, admin)
    tagged = _tagged(client, headers, opp["id"], sap, [sap_type])

    edited = _patch(
        client, headers, opp["id"], tagged, {"classification": "data"}, tagged["row_version"]
    )

    assert edited.status_code == 200, edited.text
    assert _ids(edited.json()) == [sap_type]
    listed = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()
    assert listed["untagged_integration_count"] == 1
