"""The outdated-Assessments read (Story 2.7): `GET …/assessments/outdated` lists the current
Assessments with a Requirement pin (a Finding's or an effort row's) older than that
Requirement's current version, or whose Requirement is no longer active. Against a real,
migrated Postgres as psa_app, with the per-agent fake gateway and hidden jobs."""

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_specialists import (
    AgentGateway,
    assessment_out,
    effort,
    finding,
    install,
    prepared,
    replies,
    started,
)
from tests.test_intake_extraction import ASSESS, BASE, FakeGateway, drain, owner
from tests.test_intake_requirement_edits import _list, _patch
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run


def _outdated(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/assessments/outdated", headers=headers)


def _assessed(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any]]:
    """R1 (SAP) and R2 (uptime). Engineering cites R1 in a Finding and sizes R1 and R2; PM
    cites and sizes R2; Security cites R2."""
    headers, opp = prepared(client, engine, db_url, gateway, count=2)
    install(
        AgentGateway(
            replies(
                engineering_agent=[
                    assessment_out(
                        finding("SAP custom fields", ["R1"]),
                        efforts=(effort("R1", 8), effort("R2", 4)),
                    )
                ],
                pm_agent=[
                    assessment_out(finding("24/7 hypercare", ["R2"]), efforts=(effort("R2", 2),))
                ],
                security_agent=[assessment_out(finding("Remote access at night", ["R2"]))],
            )
        )
    )
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    return headers, opp


def test_nothing_is_outdated_while_the_pinned_versions_are_current(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = _assessed(client, sync_engine, db_url, gateway)

    response = _outdated(client, headers, opp["id"])

    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_an_assessment_that_pinned_an_older_version_is_listed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = _assessed(client, sync_engine, db_url, gateway)
    sap = _list(client, headers, opp["id"])[0]
    assert _patch(
        client, headers, opp["id"], sap, {"text": "Connect to SAP S/4."}, sap["row_version"]
    ).is_success  # R1 is now v2

    (item,) = _outdated(client, headers, opp["id"]).json()["items"]

    assert (item["agent"], item["label"], item["requirement_labels"]) == (
        "engineering_agent",
        "Engineering Agent",
        ["R1"],
    )
    assert item["id"]


def test_a_requirement_no_longer_active_makes_its_assessments_outdated(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = _assessed(client, sync_engine, db_url, gateway)
    sap = _list(client, headers, opp["id"])[0]
    assert _patch(
        client, headers, opp["id"], sap, {"text": "Connect to SAP S/4."}, sap["row_version"]
    ).is_success
    extraction_tests.supersede(sync_engine, opp["id"], "Runs 24/7.")

    items = _outdated(client, headers, opp["id"]).json()["items"]

    assert [(i["agent"], i["requirement_labels"]) for i in items] == [
        ("engineering_agent", ["R1", "Superseded"]),
        ("pm_agent", ["Superseded"]),
        ("security_agent", ["Superseded"]),
    ]


def test_with_no_assessment_the_list_is_empty(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = owner(client, sync_engine)
    assert _outdated(client, headers, opp["id"]).json() == {"items": []}


def test_readers_of_the_opportunity_may_read_it(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = _assessed(client, sync_engine, db_url, gateway)
    opp = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    assert _outdated(client, rep, opp["id"]).status_code == 200
    assert _outdated(client, reader, opp["id"]).status_code == 200
    hidden = _outdated(client, outsider, opp["id"])
    assert hidden.status_code == 404 and hidden.json()["code"] == "not_found"
    assert _outdated(client, headers, "nope").status_code == 422
    assert client.get(f"{BASE}/{uuid4()}/assessments/outdated").status_code == 401
