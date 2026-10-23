"""Deterministic Gaps from mandatory Checklist items (Story 4.2) against a real, migrated
Postgres as psa_app: the `gaps.detect_gaps` job's first step over the spec's I/O matrix.
Every applicable, unanswered mandatory item raises exactly one Gap (the FR-11 bar), on reruns
and concurrent runs too; settled Gaps are never raised again or reopened; a new version
raises only its new items; a Gap whose Checklist no longer applies is kept and flagged, and
only then can be dismissed; the Gaps commit even when the agent is disabled or fails; and a
re-detection never supersedes them.

Every Opportunity here has a unique product and industry, so only the Checklists the test
publishes apply to it.
"""

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.gaps.application.mandatory import raise_mandatory_gaps
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.model_gateway.port import ModelUnavailableError
from app.platform.uow import unit_of_work
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_gaps_detection import (
    ITEMS,
    NOTE,
    detections,
    events,
    gap,
    gaps_out,
    question_rows,
    requeue,
    rows,
)
from tests.test_gaps_questions import _gaps, _if_match
from tests.test_health import assert_problem
from tests.test_intake_extraction import (
    BASE,
    DETECT,
    EXTRACT,
    MINE,
    PARSE,
    FakeGateway,
    drain,
    out,
    upload,
)
from tests.test_knowledge_checklists import BASE as CHECKLISTS
from tests.test_knowledge_checklists import (
    _author,
    _create,
    _draft,
    _entry,
    _item,
    _published,
    _saved,
)
from tests.test_opportunities import PSE, _user
from tests.test_opportunities import _create as _create_opportunity
from tests.test_role_admin import _admin

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile

MANDATORY = "mandatory_checklist"
RAISED = "gaps.gap.raised"


# --- helpers --------------------------------------------------------------------------------


def scoped(
    client: TestClient,
    engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    *,
    extract: bool = True,
) -> tuple[dict[str, str], dict[str, Any], str, str]:
    """An Opportunity with a unique product and industry; with `extract`, its Sources parsed
    and two Requirements extracted (its Gap detection queued). Returns the owner's headers,
    the Opportunity, its product and its industry."""
    tag = uuid4().hex[:10]
    product, industry = f"Product {tag}", f"Industry {tag}"
    headers, _ = _user(client, engine, "Owner Person", PSE)
    opp = _create_opportunity(client, headers, products=[product], industry=industry)
    MINE.append(UUID(opp["id"]))
    if extract:
        upload(client, headers, opp["id"], "n.txt", f"{NOTE}{uuid4()}")
        assert drain(db_url, PARSE) == ["succeeded"]
        gateway.replies = [out(*ITEMS[:2])]
        assert drain(db_url, EXTRACT) == ["succeeded"]
    return headers, opp, product, industry


def publish(
    client: TestClient,
    author: dict[str, str],
    *,
    items: list[dict[str, Any]],
    domain: str = "security",
    **scope: Any,
) -> dict[str, Any]:
    """A published v1 Checklist with these items and scope (`products` / `industry`)."""
    checklist = _create(client, author, domain=domain)
    ready = _saved(client, author, checklist, items=items, **{"products": [], **scope})
    return _published(client, author, ready)


def republish(
    client: TestClient, author: dict[str, str], published: dict[str, Any], items: Any
) -> dict[str, Any]:
    """The next version of `published`, its items replaced by `items(current_items)`."""
    url = f"{CHECKLISTS}/{published['id']}"
    opened = client.post(f"{url}/draft", headers={**author, **_if_match(published["row_version"])})
    assert opened.status_code == 200, opened.text
    draft = opened.json()
    saved = _saved(client, author, draft, items=items(_draft(draft)["items"]))
    return _published(client, author, saved)


def retire(client: TestClient, author: dict[str, str], published: dict[str, Any]) -> None:
    resp = client.post(
        f"{CHECKLISTS}/{published['id']}/retire",
        headers={**author, **_if_match(published["row_version"])},
        json={"reason": "No longer used"},
    )
    assert resp.status_code == 200, resp.text


def mandatory_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM gaps_gaps WHERE opportunity_id = :o AND origin = :m ORDER BY created_at, id",
        o=opp_id,
        m=MANDATORY,
    )


def detect(db_url: str, gateway: FakeGateway, *candidates: dict[str, Any]) -> list[str]:
    gateway.replies = [gaps_out(*candidates)]
    return drain(db_url, DETECT)


def rerun(db_url: str, gateway: FakeGateway, opp_id: str, *candidates: dict[str, Any]) -> None:
    requeue(db_url, opp_id)
    assert detect(db_url, gateway, *candidates) == ["succeeded"]


def dismiss(
    client: TestClient, headers: dict[str, str], opp_id: str, gap_view: dict[str, Any]
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/gaps/{gap_view['id']}/dismiss",
        headers={**headers, **_if_match(gap_view["row_version"])},
        json={"reason_kind": "not_relevant"},
    )


def two_checklists(
    client: TestClient, product: str, industry: str, *, affected: str | None = None
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """By product: 2 mandatory items and 1 optional; by industry: 1 mandatory (its affected
    area `affected`) and 1 optional. 3 mandatory items in all."""
    author = _author(client)
    by_product = publish(
        client,
        author,
        products=[product],
        items=[
            _item(text="Is SSO required?", mandatory=True, impact="medium"),
            _item(text="Optional detail?"),
            _item(text="Is a pen test required?", mandatory=True, impact="high"),
        ],
    )
    by_industry = publish(
        client,
        author,
        domain="commercial",
        industry=industry,
        items=[
            _item(
                text="Which payment terms?",
                mandatory=True,
                impact="high",
                affected_entry_id=affected,
            ),
            _item(text="Optional nicety?"),
        ],
    )
    return author, by_product, by_industry


@pytest.fixture
def restore_clarification_agent(sync_engine: Engine) -> Iterator[None]:
    yield
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE registry_agents SET status = 'active', row_version = row_version + 1 "
                "WHERE agent_id = 'clarification_agent' AND status <> 'active'"
            )
        )


# --- the first run --------------------------------------------------------------------------


def test_every_applicable_mandatory_item_raises_exactly_one_gap(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    admin, _ = _admin(client)
    package = _entry(client, admin, "work_package")
    _, by_product, by_industry = two_checklists(client, product, industry, affected=package)

    assert detect(db_url, gateway, gap("SAP interface type", ["R1"])) == ["succeeded"]

    mandatory = mandatory_rows(sync_engine, opp["id"])
    assert sorted(g["title"] for g in mandatory) == [
        "Is SSO required?",
        "Is a pen test required?",
        "Which payment terms?",
    ]
    (detection,) = detections(sync_engine, opp["id"])
    for row in mandatory:
        assert (row["status"], row["detection_id"], row["checklist_applies"]) == (
            "open",
            detection["id"],
            True,
        )
        assert (
            rows(sync_engine, "SELECT * FROM gaps_gap_requirements WHERE gap_id = :g", g=row["id"])
            == []
        )
        (question,) = question_rows(sync_engine, row["id"])
        assert (question["status"], question["from_checklist"], question["text"]) == (
            "drafted",
            True,
            row["title"],
        )
    payment = next(g for g in mandatory if g["title"] == "Which payment terms?")
    assert payment["category"] == "commercial"
    assert str(payment["why_entry_id"]) == package
    assert {g["why_entry_id"] for g in mandatory if g["id"] != payment["id"]} == {None}
    assert payment["impact_basis"] == (
        f'Default impact of mandatory item in Checklist "{by_industry["name"]}" v1.'
    )
    item_id = by_industry["items"][0]["id"]
    assert payment["trigger"] == {
        "kind": "checklist_item",
        "checklist_id": by_industry["id"],
        "version": 1,
        "item_id": item_id,
        "checklist_name": by_industry["name"],
    }

    # The agent step still ran.
    detected = rows(
        sync_engine,
        "SELECT * FROM gaps_gaps WHERE opportunity_id = :o AND origin = 'detected'",
        o=opp["id"],
    )
    assert [g["title"] for g in detected] == ["SAP interface type"]

    # One `gaps.gap.raised` per mandatory Gap, by the system, ids and counts only.
    raised = [
        e
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == RAISED and e["payload"].get("origin") == MANDATORY
    ]
    assert len(raised) == 3
    for event in raised:
        assert (event["actor_type"], event["actor_id"]) == ("system", "gaps.detect_gaps")
        assert event["payload"]["requirement_ids"] == []
        assert "SSO" not in str(event["payload"]) and "payment" not in str(event["payload"])
    # One `gaps.clarification_question.drafted` per mandatory question, by the system.
    questions = {str(question_rows(sync_engine, g["id"])[0]["id"]): str(g["id"]) for g in mandatory}
    drafted = [
        e
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "gaps.clarification_question.drafted"
        and e["payload"]["gap_id"] in questions.values()
    ]
    assert len(drafted) == 3
    for event in drafted:
        assert (event["actor_type"], event["actor_id"]) == ("system", "gaps.detect_gaps")
        assert event["subject_type"] == "gaps.clarification_question"
        assert questions[str(event["subject_id"])] == event["payload"]["gap_id"]

    # The list: impact, then mandatory first within an impact, then oldest.
    items = _gaps(client, headers, opp["id"])["items"]
    order = [(g["impact"], g["origin"], g["title"]) for g in items]
    assert order[:3] == [
        ("high", MANDATORY, "Is a pen test required?"),
        ("high", MANDATORY, "Which payment terms?"),
        ("high", "detected", "SAP interface type"),
    ] or order[:3] == [
        ("high", MANDATORY, "Which payment terms?"),
        ("high", MANDATORY, "Is a pen test required?"),
        ("high", "detected", "SAP interface type"),
    ]
    assert order[3] == ("medium", MANDATORY, "Is SSO required?")
    view = next(g for g in items if g["title"] == "Which payment terms?")
    assert view["trigger"]["kind"] == "checklist_item"
    assert view["checklist_applies"] is True
    assert view["requirements"] == []
    assert view["question"]["from_checklist"] is True
    assert view["question"]["topic"] == by_industry["name"]
    assert view["why_entry_id"] == package
    agent_view = next(g for g in items if g["origin"] == "detected")
    assert agent_view["question"]["from_checklist"] is False
    assert by_product["id"] in {g["trigger"].get("checklist_id") for g in items}


def test_reruns_and_redetection_keep_one_gap_per_item_and_never_supersede_them(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    two_checklists(client, product, industry)
    assert detect(db_url, gateway, gap("SAP interface type", ["R1"])) == ["succeeded"]
    first = {g["id"] for g in mandatory_rows(sync_engine, opp["id"])}

    rerun(db_url, gateway, opp["id"], gap("Uptime", ["R2"]))
    rerun(db_url, gateway, opp["id"], gap("Uptime", ["R2"]))

    again = mandatory_rows(sync_engine, opp["id"])
    assert {g["id"] for g in again} == first
    assert {g["status"] for g in again} == {"open"}
    superseded = rows(
        sync_engine,
        "SELECT title FROM gaps_gaps WHERE opportunity_id = :o AND status = 'superseded'",
        o=opp["id"],
    )
    assert {r["title"] for r in superseded} == {"SAP interface type", "Uptime"}
    raised = [e for e in events(sync_engine, opp["id"]) if e["payload"].get("origin") == MANDATORY]
    assert len(raised) == 3


def test_concurrent_runs_raise_each_gap_once(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    two_checklists(client, product, industry)
    (detection,) = detections(sync_engine, opp["id"])

    async def scenario() -> list[int]:
        engines = [create_engine(Settings(database_url=db_url)) for _ in range(2)]
        try:

            async def one(index: int) -> int:
                async with unit_of_work(engines[index]) as uow:
                    outcome = await raise_mandatory_gaps(
                        uow, UUID(opp["id"]), UUID(str(detection["id"]))
                    )
                    await asyncio.sleep(0.2)  # hold the transaction open
                    return outcome.raised

            return list(await asyncio.gather(one(0), one(1)))
        finally:
            for engine in engines:
                await engine.dispose()

    raised = run_async(scenario())

    assert sum(raised) == 3
    assert len(mandatory_rows(sync_engine, opp["id"])) == 3


def test_a_settled_gap_is_never_raised_again_nor_reopened(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    two_checklists(client, product, industry)
    assert detect(db_url, gateway) == ["succeeded"]
    settled = mandatory_rows(sync_engine, opp["id"])[0]
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE gaps_gaps SET status = 'converted', converted_to = 'condition' "
                "WHERE id = :g"
            ),
            {"g": settled["id"]},
        )

    rerun(db_url, gateway, opp["id"])

    after = mandatory_rows(sync_engine, opp["id"])
    assert len(after) == 3
    assert next(g for g in after if g["id"] == settled["id"])["status"] == "converted"


def test_a_new_version_raises_only_its_new_mandatory_item(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    author, by_product, _ = two_checklists(client, product, industry)
    assert detect(db_url, gateway) == ["succeeded"]
    before = {g["id"] for g in mandatory_rows(sync_engine, opp["id"])}

    republish(
        client,
        author,
        by_product,
        lambda items: [*items, _item(text="Are backups required?", mandatory=True)],
    )
    rerun(db_url, gateway, opp["id"])

    after = mandatory_rows(sync_engine, opp["id"])
    new = [g for g in after if g["id"] not in before]
    assert [g["title"] for g in new] == ["Are backups required?"]
    assert new[0]["trigger"]["version"] == 2
    assert before <= {g["id"] for g in after}
    assert all(g["checklist_applies"] for g in after)


def test_a_gap_whose_checklist_no_longer_applies_is_kept_flagged_and_dismissable(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    author, by_product, by_industry = two_checklists(client, product, industry)
    assert detect(db_url, gateway) == ["succeeded"]
    payment = next(
        g
        for g in _gaps(client, headers, opp["id"])["items"]
        if g["title"] == "Which payment terms?"
    )

    # Dismissing while it applies: 409, nothing written.
    refused = dismiss(client, headers, opp["id"], payment)
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert_problem(body, 409, "gap_mandatory")
    assert body["detail"] == (
        "A mandatory Gap can be dismissed only once its Checklist no longer applies."
    )
    (row,) = rows(sync_engine, "SELECT * FROM gaps_gaps WHERE id = :g", g=payment["id"])
    assert (row["status"], row["row_version"]) == ("open", payment["row_version"])

    # The industry Checklist retired, the product one loses its pen-test item in v2.
    retire(client, author, by_industry)
    republish(
        client,
        author,
        by_product,
        lambda items: [i for i in items if i["text"] != "Is a pen test required?"],
    )
    rerun(db_url, gateway, opp["id"])

    flags = {g["title"]: g["checklist_applies"] for g in mandatory_rows(sync_engine, opp["id"])}
    assert flags == {
        "Is SSO required?": True,
        "Is a pen test required?": False,
        "Which payment terms?": False,
    }
    payment = next(
        g
        for g in _gaps(client, headers, opp["id"])["items"]
        if g["title"] == "Which payment terms?"
    )
    assert (payment["status"], payment["checklist_applies"]) == ("open", False)
    dismissed = dismiss(client, headers, opp["id"], payment)
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"


def test_a_gap_applies_again_when_scope_returns(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    author, by_product, _ = two_checklists(client, product, industry)
    assert detect(db_url, gateway) == ["succeeded"]
    v2 = republish(
        client, author, by_product, lambda items: [{**i, "mandatory": False} for i in items]
    )
    rerun(db_url, gateway, opp["id"])
    assert sum(not g["checklist_applies"] for g in mandatory_rows(sync_engine, opp["id"])) == 2

    republish(
        client,
        author,
        v2,
        lambda items: [{**i, "mandatory": i["text"] != "Optional detail?"} for i in items],
    )
    rerun(db_url, gateway, opp["id"])

    after = mandatory_rows(sync_engine, opp["id"])
    assert len(after) == 3
    assert all(g["checklist_applies"] for g in after)


def test_a_reopened_gap_whose_checklist_applies_again_cannot_be_dismissed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    author, by_product, _ = two_checklists(client, product, industry)
    assert detect(db_url, gateway) == ["succeeded"]
    v2 = republish(
        client, author, by_product, lambda items: [{**i, "mandatory": False} for i in items]
    )
    rerun(db_url, gateway, opp["id"])

    def sso() -> dict[str, Any]:
        items = _gaps(client, headers, opp["id"])["items"]
        return next(g for g in items if g["title"] == "Is SSO required?")

    dismissed = dismiss(client, headers, opp["id"], sso())
    assert dismissed.status_code == 200, dismissed.text
    republish(
        client,
        author,
        v2,
        lambda items: [{**i, "mandatory": i["text"] != "Optional detail?"} for i in items],
    )
    rerun(db_url, gateway, opp["id"])
    (row,) = rows(sync_engine, "SELECT * FROM gaps_gaps WHERE id = :g", g=sso()["id"])
    assert (row["status"], row["checklist_applies"]) == ("dismissed", True)

    current = sso()
    reopened = client.post(
        f"{BASE}/{opp['id']}/gaps/{current['id']}/reopen",
        headers={**headers, **_if_match(current["row_version"])},
        json={"reason": "Back in scope"},
    )
    assert reopened.status_code == 200, reopened.text
    refused = dismiss(client, headers, opp["id"], reopened.json())
    assert refused.status_code == 409, refused.text
    assert_problem(refused.json(), 409, "gap_mandatory")


def test_a_newer_mandatory_gap_is_listed_before_an_older_detected_one(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, product, _ = scoped(client, sync_engine, db_url, gateway)
    assert detect(db_url, gateway, gap("SAP interface type", ["R1"])) == ["succeeded"]
    with sync_engine.begin() as conn:  # a person touched it: re-detection keeps it
        conn.execute(
            sa.text("UPDATE gaps_gaps SET touched_by_human = true WHERE opportunity_id = :o"),
            {"o": opp["id"]},
        )
    publish(
        client,
        _author(client),
        products=[product],
        items=[_item(text="Is a pen test required?", mandatory=True, impact="high")],
    )

    rerun(db_url, gateway, opp["id"])

    items = _gaps(client, headers, opp["id"])["items"]
    assert [(g["origin"], g["title"]) for g in items] == [
        (MANDATORY, "Is a pen test required?"),
        ("detected", "SAP interface type"),
    ]
    assert items[0]["created_at"] > items[1]["created_at"]


# --- the agent step failing -----------------------------------------------------------------


def test_mandatory_gaps_commit_while_the_agent_is_disabled(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_clarification_agent: None,
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    two_checklists(client, product, industry)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE registry_agents SET status = 'disabled', row_version = row_version + 1 "
                "WHERE agent_id = 'clarification_agent'"
            )
        )
    calls = len(gateway.requests)

    assert drain(db_url, DETECT) == ["succeeded"]

    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["error_code"]) == ("failed", "registry_agent_disabled")
    assert len(gateway.requests) == calls
    assert len(mandatory_rows(sync_engine, opp["id"])) == 3


def test_mandatory_gaps_stay_open_with_checklist_questions_when_the_agent_fails(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, product, industry = scoped(client, sync_engine, db_url, gateway)
    two_checklists(client, product, industry)
    gateway.replies = [ModelUnavailableError("down")]

    assert drain(db_url, DETECT) == ["failed_retrying", "dead"]

    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["error_code"]) == ("failed", "model_unavailable")
    items = _gaps(client, headers, opp["id"])["items"]
    assert len(items) == 3
    for item in items:
        assert (item["origin"], item["status"]) == (MANDATORY, "open")
        assert item["question"]["from_checklist"] is True
        assert item["question"]["status"] == "drafted"
    # Both attempts ran the mandatory step; the second raised nothing new.
    assert len([e for e in events(sync_engine, opp["id"]) if e["event_type"] == RAISED]) == 3


def test_with_no_requirements_the_mandatory_gaps_are_still_raised(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, product, industry = scoped(client, sync_engine, db_url, gateway, extract=False)
    two_checklists(client, product, industry)
    requeue(db_url, opp["id"])
    gateway.replies = [ModelUnavailableError("must not be called")]

    assert drain(db_url, DETECT) == ["succeeded"]

    assert gateway.requests == []
    assert len(mandatory_rows(sync_engine, opp["id"])) == 3


def test_an_opportunity_no_checklist_matches_gets_no_mandatory_gap(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _, _ = scoped(client, sync_engine, db_url, gateway)
    two_checklists(client, f"Other {uuid4().hex}", f"Other {uuid4().hex}")

    assert detect(db_url, gateway) == ["succeeded"]

    assert mandatory_rows(sync_engine, opp["id"]) == []
