"""Setting the Baseline (Story 9.7) against a real, migrated Postgres as psa_app: the shared
per-Opportunity lock key, then every row of the story's matrix (the first Baseline, a
replacement, not newer, no Review Request, a reopened blocker, agent and system callers, a
stale `If-Match`, a rejection racing the Baseline, submitting after a Baseline), the approvers
read, the version list and `?version=`, the derived Opportunity status and list summary,
append-only grants and the migration's down/up.

Estimate Versions are inserted directly and reviewed through the API; people sign in through
`/me` with their roles (see `test_reviews_requests`).
"""

import asyncio
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.estimates.application import public as estimates
from app.modules.gaps.application import public as gaps
from app.modules.gaps.application.public import GapReopening
from app.modules.identity.application.public import Action, Principal, Role
from app.modules.reviews.application import public as reviews
from app.modules.reviews.application.public import Decision, ReviewDecisionCreate
from app.platform.actor import Actor
from app.platform.errors import BaselineBlockedError, ForbiddenError
from app.platform.locks import opportunity_lock_key
from app.platform.uow import unit_of_work
from tests import test_opportunities as opportunity_tests
from tests.conftest import run_async
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import BASE, PSE, _conflict, _create, _gap, _user
from tests.test_reviews_decisions import _decide, _sent
from tests.test_reviews_requests import PM, REP, _events, _row_version, _send, _status, _version

client = opportunity_tests.client

SET = "estimates.baseline.set"


# --- helpers --------------------------------------------------------------------------------


def _set(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    version_id: str,
    row_version: int | None,
) -> Any:
    extra = {} if row_version is None else {"If-Match": f'"{row_version}"'}
    return client.post(
        f"{BASE}/{opp_id}/estimate-versions/{version_id}/baseline", headers={**headers, **extra}
    )


def _set_now(
    client: TestClient, engine: Engine, headers: dict[str, str], opp_id: str, vid: str
) -> Any:
    return _set(client, headers, opp_id, vid, _row_version(engine, vid))


def _estimate(
    client: TestClient, headers: dict[str, str], opp_id: str, version: int | None = None
) -> Any:
    query = "" if version is None else f"?version={version}"
    return client.get(f"{BASE}/{opp_id}/estimate{query}", headers=headers)


def _gate(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{opp_id}/submission-blockers", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _baselines(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM estimates_baselines WHERE opportunity_id = :o ORDER BY set_at",
        o=opp_id,
    )


def _list_row(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    items = client.get(f"{BASE}?scope=mine&page_size=200", headers=headers).json()["items"]
    return next(i for i in items if i["id"] == opp_id)


def _approved(
    client: TestClient, engine: Engine
) -> tuple[dict[str, str], UUID, dict[str, Any], str, list[tuple[dict[str, str], UUID]]]:
    """`_sent` with Ana (engineering) and Pia (PM) both approving v3: v3 is `approved` and
    nothing blocks the Baseline. (owner headers, owner id, opp, v3, [(headers, id)])."""
    headers, owner_id, opp, v3, [(ana_h, ana)], [eng] = _sent(client, engine, "Ana Reviewer")
    pia_h, pia = _user(client, engine, "Pia Planner", PM)
    sent = _send(client, headers, opp["id"], v3, _row_version(engine, v3), [pia], "pm")
    assert sent.status_code == 201, sent.text
    (pm,) = sent.json()["items"]
    assert _decide(client, ana_h, opp["id"], eng, "approved", reason=None).status_code == 201
    assert _decide(client, pia_h, opp["id"], pm, "approved", reason=None).status_code == 201
    assert _status(engine, v3) == "approved"
    return headers, owner_id, opp, v3, [(ana_h, ana), (pia_h, pia)]


def _submit(
    client: TestClient, engine: Engine, headers: dict[str, str], opp_id: str, vid: str
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/estimate/versions/{vid}/submit",
        headers={**headers, "If-Match": f'"{_row_version(engine, vid)}"'},
    )


def _new_version(client: TestClient, headers: dict[str, str], opp_id: str, vid: str) -> str:
    resp = client.post(
        f"{BASE}/{opp_id}/estimate-versions/{vid}/new-version",
        headers=headers,
        json={"reason": "Customer added a warehouse"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def _approve_alone(
    client: TestClient,
    engine: Engine,
    headers: dict[str, str],
    opp_id: str,
    vid: str,
    reviewer: tuple[dict[str, str], UUID],
) -> None:
    sent = _send(client, headers, opp_id, vid, _row_version(engine, vid), [reviewer[1]])
    assert sent.status_code == 201, sent.text
    (request,) = sent.json()["items"]
    assert _decide(client, reviewer[0], opp_id, request, "approved", reason=None).status_code == 201
    assert _status(engine, vid) == "approved"


# --- the lock key (no DB) -------------------------------------------------------------------


def test_the_lock_key_is_the_uuids_first_8_bytes_signed_big_endian() -> None:
    assert opportunity_lock_key(UUID("00000000-0000-0001-ffff-ffffffffffff")) == 1
    assert opportunity_lock_key(UUID("ffffffff-ffff-ffff-0000-000000000000")) == -1
    assert opportunity_lock_key(UUID("80000000-0000-0000-0000-000000000000")) == -(2**63)


# --- the matrix -----------------------------------------------------------------------------


def test_the_first_baseline(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id, opp, v3, [(_, ana), (_, pia)] = _approved(client, sync_engine)
    gate = _gate(client, headers, opp["id"])
    assert gate["to_baseline"] == []
    assert gate["is_baseline"] is False
    assert gate["can_set_baseline"] is True
    assert _list_row(client, headers, opp["id"])["status"] == "intake"

    resp = _set_now(client, sync_engine, headers, opp["id"], v3)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["version_id"], body["version"]) == (v3, 3)
    assert (body["previous_version_id"], body["previous_version"]) == (None, None)
    assert body["set_by_name"] == "Owner Person"
    (row,) = _baselines(sync_engine, opp["id"])
    assert (str(row["estimate_version_id"]), row["previous_version_id"]) == (v3, None)
    assert str(row["set_by"]) == str(owner_id)
    assert _status(sync_engine, v3) == "approved"

    (event,) = _events(sync_engine, opp["id"], SET)
    payload = event["payload"]
    assert (payload["version_id"], payload["version"]) == (v3, 3)
    assert (payload["previous_version_id"], payload["previous_version"]) == (None, None)
    assert payload["baseline_id"] == str(row["id"])
    assert [(a["user_id"], a["review_type"]) for a in payload["approvers"]] == [
        (str(ana), "engineering"),
        (str(pia), "pm"),
    ]
    assert all(a["decision_id"] for a in payload["approvers"])
    assert (event["actor_type"], event["actor_id"]) == ("user", str(owner_id))
    assert (event["subject_type"], str(event["subject_id"])) == ("estimates.estimate_version", v3)

    estimate = _estimate(client, headers, opp["id"]).json()
    assert estimate["baseline"]["version_id"] == v3
    assert estimate["baseline"]["version"] == 3
    assert estimate["baseline"]["set_by_name"] == "Owner Person"
    assert estimate["is_current"] is True
    assert _gate(client, headers, opp["id"])["is_baseline"] is True
    row_ = _list_row(client, headers, opp["id"])
    assert row_["status"] == "baselined"
    assert row_["estimate"]["is_baseline"] is True
    opened = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert opened["status"] == "baselined"
    filtered = client.get(f"{BASE}?scope=mine&status=baselined&page_size=200", headers=headers)
    assert opp["id"] in {i["id"] for i in filtered.json()["items"]}


def test_the_approvers_read(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)

    resp = client.get(f"{BASE}/{opp['id']}/estimate-versions/{v3}/approvers", headers=headers)

    assert resp.status_code == 200, resp.text
    found = resp.json()
    assert [(a["name"], a["review_type"], a["status"]) for a in found] == [
        ("Ana Reviewer", "engineering", "approved"),
        ("Pia Planner", "pm", "approved"),
    ]
    assert all(a["decided_at"] and a["decision_id"] for a in found)
    missing = client.get(
        f"{BASE}/{opp['id']}/estimate-versions/{opp['id']}/approvers", headers=headers
    )
    assert_problem(missing.json(), 404, "not_found")


def test_submit_after_a_baseline_then_replace_it(client: TestClient, sync_engine: Engine) -> None:
    """Baseline v3; New version v4 and submit it: v3 stays `approved` and the Baseline. v4
    approved replaces it (`previous` v3), and v3 keeps `approved` without the marker."""
    headers, _, opp, v3, [ana, _] = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    v4 = _new_version(client, headers, opp["id"], v3)

    submitted = _submit(client, sync_engine, headers, opp["id"], v4)

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["superseded_count"] == 0
    assert _status(sync_engine, v3) == "approved"
    gate = _gate(client, headers, opp["id"])
    assert gate["version"]["id"] == v4
    assert gate["is_baseline"] is False
    assert [b["kind"] for b in gate["to_baseline"]] == ["no_review_request"]
    assert _estimate(client, headers, opp["id"]).json()["baseline"]["version_id"] == v3

    _approve_alone(client, sync_engine, headers, opp["id"], v4, ana)
    resp = _set_now(client, sync_engine, headers, opp["id"], v4)

    assert resp.status_code == 201, resp.text
    assert (resp.json()["previous_version_id"], resp.json()["previous_version"]) == (v3, 3)
    assert [str(r["estimate_version_id"]) for r in _baselines(sync_engine, opp["id"])] == [v3, v4]
    assert _status(sync_engine, v3) == "approved"
    events = _events(sync_engine, opp["id"], SET)
    assert [e["payload"]["previous_version"] for e in events] == [None, 3]
    assert _estimate(client, headers, opp["id"]).json()["baseline"]["version"] == 4

    # A later submit supersedes the replaced Baseline like any other approved version.
    v5 = _new_version(client, headers, opp["id"], v4)
    assert _submit(client, sync_engine, headers, opp["id"], v5).status_code == 200
    assert _status(sync_engine, v3) == "superseded"
    assert _status(sync_engine, v4) == "approved"


def test_only_a_newer_approved_version_replaces_the_baseline(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [ana, _] = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    v4 = _new_version(client, headers, opp["id"], v3)
    assert _submit(client, sync_engine, headers, opp["id"], v4).status_code == 200
    _approve_alone(client, sync_engine, headers, opp["id"], v4, ana)
    assert _set_now(client, sync_engine, headers, opp["id"], v4).status_code == 201
    v5 = _new_version(client, headers, opp["id"], v4)  # a draft

    for vid in (v3, v4, v5):
        resp = _set_now(client, sync_engine, headers, opp["id"], vid)
        body = resp.json()
        assert_problem(body, 409, "baseline_not_newer")
        assert body["detail"] == ("Only a newer approved Estimate Version can replace the Baseline")
    assert len(_baselines(sync_engine, opp["id"])) == 2


def test_no_review_request_blocks_the_baseline(client: TestClient, sync_engine: Engine) -> None:
    """A version approved without any Review Request (older data) is gated."""
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    v3 = _version(sync_engine, opp["id"], 3, status="approved", created_by=owner_id)

    gate = _gate(client, headers, opp["id"])
    (blocker,) = gate["to_baseline"]
    assert blocker["kind"] == "no_review_request"
    assert blocker["title"] == "No Review Request sent yet"
    assert blocker["href"] == f"/opportunities/{opp['id']}/estimate"

    resp = _set_now(client, sync_engine, headers, opp["id"], v3)

    body = resp.json()
    assert_problem({k: v for k, v in body.items() if k != "blockers"}, 409, "baseline_blocked")
    assert [b["kind"] for b in body["blockers"]] == ["no_review_request"]
    assert _baselines(sync_engine, opp["id"]) == []
    assert _events(sync_engine, opp["id"], SET) == []


def test_a_reopened_blocker_blocks_the_baseline(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    _conflict(sync_engine, opp["id"], "open")  # raised after the approval

    gate = _gate(client, headers, opp["id"])
    assert [b["kind"] for b in gate["to_baseline"]] == ["conflict"]
    assert gate["to_submit"] == []
    estimate = _estimate(client, headers, opp["id"]).json()
    assert [b["kind"] for b in estimate["blockers"]["to_baseline"]] == ["conflict"]

    resp = _set_now(client, sync_engine, headers, opp["id"], v3)

    body = resp.json()
    assert_problem({k: v for k, v in body.items() if k != "blockers"}, 409, "baseline_blocked")
    assert [b["kind"] for b in body["blockers"]] == ["conflict"]
    assert body["detail"] == "Resolve 1 blocker before you can set the Baseline."
    assert _baselines(sync_engine, opp["id"]) == []


def test_a_version_not_approved_is_blocked(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _, [request] = _sent(client, sync_engine, "Ana Reviewer")

    resp = _set_now(client, sync_engine, headers, opp["id"], v3)

    body = resp.json()
    assert_problem({k: v for k, v in body.items() if k != "blockers"}, 409, "baseline_blocked")
    assert [(b["kind"], b["subject_id"]) for b in body["blockers"]] == [
        ("review_request", request["id"])
    ]


@pytest.mark.parametrize("actor_type", ["agent", "system"])
def test_no_agent_or_system_actor_may_set_it(
    client: TestClient, sync_engine: Engine, db_url: str, actor_type: str
) -> None:
    _, owner_id, opp, v3, _ = _approved(client, sync_engine)
    principal = Principal(
        Actor(actor_type, str(owner_id)),  # type: ignore[arg-type]
        frozenset({Role.PRESALES_ENGINEER}),
        frozenset(Action),
    )

    async def attempt() -> BaseException | None:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        try:
            async with unit_of_work(engine) as uow:
                await estimates.set_baseline(
                    uow,
                    principal,
                    UUID(opp["id"]),
                    UUID(v3),
                    f'"{_row_version(sync_engine, v3)}"',
                )
        except ForbiddenError as exc:
            return exc
        finally:
            await engine.dispose()
        return None

    assert isinstance(run_async(attempt()), ForbiddenError)
    assert _baselines(sync_engine, opp["id"]) == []


def test_who_may_set_it(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, [(ana_h, _), _] = _approved(client, sync_engine)
    rep_h, rep = _user(client, sync_engine, "Sam Sales", REP)
    opened = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    added = client.put(
        f"{BASE}/{opp['id']}/collaborators/{rep}",
        headers={**headers, "If-Match": f'"{opened["row_version"]}"'},
    )
    assert added.status_code in (200, 201, 204), added.text
    stranger_h, _ = _user(client, sync_engine, "Someone Else", PSE)

    assert _set_now(client, sync_engine, rep_h, opp["id"], v3).status_code == 403
    assert _gate(client, rep_h, opp["id"])["can_set_baseline"] is False
    assert _set_now(client, sync_engine, stranger_h, opp["id"], v3).status_code == 404
    assert _set_now(client, sync_engine, ana_h, opp["id"], v3).status_code in (403, 404)
    assert _baselines(sync_engine, opp["id"]) == []


def test_a_stale_or_missing_if_match(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    stale = _row_version(sync_engine, v3) - 1

    assert_problem(_set(client, headers, opp["id"], v3, stale).json(), 412, "row_version_mismatch")
    assert_problem(_set(client, headers, opp["id"], v3, None).json(), 428, "if_match_required")
    assert _baselines(sync_engine, opp["id"]) == []


# --- serialisation --------------------------------------------------------------------------


def test_a_rejection_and_the_baseline_serialise_on_the_lock(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    """The rejection holds the Opportunity's lock, uncommitted; set_baseline waits for it,
    then reads the gate again and is refused with the rejected request named. (Its
    `If-Match` is the version's row version once the rejection commits, so the rules decide,
    not the `If-Match`.)"""
    _, owner_id, opp, v3, [(_, ana)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    opp_id = UUID(opp["id"])
    owner = Principal(Actor("user", str(owner_id)), frozenset({Role.PRESALES_ENGINEER}))
    reviewer = Principal(Actor("user", str(ana)), frozenset({Role.ENGINEERING_REVIEWER}))
    after_reject = _row_version(sync_engine, v3) + 1

    async def scenario() -> tuple[bool, Any]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        decided = asyncio.Event()
        release = asyncio.Event()

        async def first() -> Any:
            async with unit_of_work(engine) as uow:
                done = await reviews.decide(
                    uow,
                    reviewer,
                    opp_id,
                    UUID(request["id"]),
                    ReviewDecisionCreate(decision=Decision.REJECTED, reason="Too high"),
                    f'"{request["row_version"]}"',
                )
                decided.set()
                await release.wait()  # hold the lock, uncommitted
                return done

        async def second() -> Any:
            await decided.wait()
            async with unit_of_work(engine) as uow:
                return await estimates.set_baseline(
                    uow, owner, opp_id, UUID(v3), f'"{after_reject}"'
                )

        try:
            t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
            await decided.wait()
            await asyncio.sleep(0.5)
            second_blocked = not t2.done()
            release.set()
            return second_blocked, await asyncio.gather(t1, t2, return_exceptions=True)
        finally:
            await engine.dispose()

    second_blocked, (a, b) = run_async(scenario())

    assert second_blocked
    assert not isinstance(a, BaseException), a
    assert isinstance(b, BaselineBlockedError), b
    assert b.extensions is not None
    (blocker,) = b.extensions["blockers"]
    assert (blocker["kind"], blocker["subject_id"]) == ("review_request", request["id"])
    assert blocker["title"].endswith("Rejected")
    assert _status(sync_engine, v3) == "rejected"
    assert _baselines(sync_engine, opp["id"]) == []


def test_the_baseline_first_holds_off_a_new_version(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    """set_baseline holds the lock, uncommitted; a New version waits for it and then copies
    the version that is now the Baseline."""
    _, owner_id, opp, v3, _ = _approved(client, sync_engine)
    opp_id = UUID(opp["id"])
    owner = Principal(Actor("user", str(owner_id)), frozenset({Role.PRESALES_ENGINEER}))
    row_version = _row_version(sync_engine, v3)

    async def scenario() -> tuple[bool, Any]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        set_ = asyncio.Event()
        release = asyncio.Event()

        async def first() -> Any:
            async with unit_of_work(engine) as uow:
                done = await estimates.set_baseline(
                    uow, owner, opp_id, UUID(v3), f'"{row_version}"'
                )
                set_.set()
                await release.wait()
                return done

        async def second() -> Any:
            await set_.wait()
            async with unit_of_work(engine) as uow:
                return await estimates.create_version(uow, owner, opp_id, UUID(v3), None)

        try:
            t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
            await set_.wait()
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
    assert len(_baselines(sync_engine, opp["id"])) == 1
    assert b.version == 4


# --- the version list and an earlier version ------------------------------------------------


def test_the_version_list_puts_the_baseline_first(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    v4 = _new_version(client, headers, opp["id"], v3)

    resp = client.get(f"{BASE}/{opp['id']}/estimate-versions", headers=headers)

    assert resp.status_code == 200, resp.text
    listed = resp.json()
    assert [(v["version"], v["status"], v["is_baseline"]) for v in listed] == [
        (3, "approved", True),
        (4, "draft", False),
        (2, "superseded", False),
        (1, "superseded", False),
    ]
    assert listed[0]["created_by_name"] == "Owner Person"
    assert listed[1]["reason"] == "Customer added a warehouse"
    assert listed[1]["id"] == v4
    assert listed[0]["reason"] is None


def test_an_earlier_version_reads_read_only(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    _new_version(client, headers, opp["id"], v3)

    current = _estimate(client, headers, opp["id"]).json()
    assert (current["version"]["version"], current["is_current"]) == (4, True)
    assert current["can_submit"] is True

    earlier = _estimate(client, headers, opp["id"], 3)

    assert earlier.status_code == 200, earlier.text
    body = earlier.json()
    assert (body["version"]["version"], body["version"]["status"]) == (3, "approved")
    assert body["is_current"] is False
    assert body["can_submit"] is False
    assert body["can_request_review"] is False
    assert body["can_create_version"] is False
    assert body["baseline"]["version"] == 3
    assert body["blockers"]["to_baseline"] == []
    assert _estimate(client, headers, opp["id"], 4).json()["is_current"] is True
    assert_problem(_estimate(client, headers, opp["id"], 99).json(), 404, "not_found")
    assert _estimate(client, headers, opp["id"], 2**31).status_code == 422
    assert _estimate(client, headers, opp["id"], 0).status_code == 422


# --- append-only and the migration ----------------------------------------------------------


def test_baselines_are_append_only(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    (row,) = _baselines(sync_engine, opp["id"])
    for statement in (
        "UPDATE estimates_baselines SET set_at = now() WHERE id = :i",
        "DELETE FROM estimates_baselines WHERE id = :i",
    ):
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(statement), {"i": row["id"]})


def test_the_migration_goes_down_and_up(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201

    _alembic("downgrade", "0050_review_outcomes")
    try:
        tables = rows(
            sync_engine,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'estimates_baselines'",
        )
        assert tables == []
    finally:
        _alembic("upgrade", "head")
    assert _baselines(sync_engine, opp["id"]) == []
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201


def test_the_review_panel_carries_the_version_gate(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, _ = _approved(client, sync_engine)
    (request, _) = rows(
        sync_engine,
        "SELECT id FROM reviews_review_requests WHERE opportunity_id = :o ORDER BY created_at",
        o=opp["id"],
    )
    panel_url = f"{BASE}/{opp['id']}/review-requests/{request['id']}/panel"

    gate = client.get(panel_url, headers=headers).json()["version_gate"]
    assert (gate["version_id"], gate["status"], gate["is_baseline"]) == (v3, "approved", False)
    assert gate["to_baseline"] == []
    assert gate["can_set_baseline"] is True
    assert gate["row_version"] == _row_version(sync_engine, v3)
    assert gate["baseline_version"] is None

    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    assert client.get(panel_url, headers=headers).json()["version_gate"]["is_baseline"] is True


def test_a_gap_reopen_and_the_baseline_serialise_on_the_lock(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    """A Gap reopen (moved onto the shared lock) holds it, uncommitted; set_baseline waits,
    then reads the gate again and is refused with the reopened Gap listed."""
    _, owner_id, opp, v3, _ = _approved(client, sync_engine)
    _gap(sync_engine, opp["id"], "dismissed")
    (gap,) = rows(sync_engine, "SELECT id FROM gaps_gaps WHERE opportunity_id = :o", o=opp["id"])
    with sync_engine.begin() as conn:  # a trigger the Gap read model accepts
        conn.execute(
            sa.text("UPDATE gaps_gaps SET trigger = CAST(:t AS jsonb) WHERE id = :i"),
            {"t": '{"kind": "agent_category", "category": "other"}', "i": gap["id"]},
        )
    opp_id = UUID(opp["id"])
    owner = Principal(Actor("user", str(owner_id)), frozenset({Role.PRESALES_ENGINEER}))
    row_version = _row_version(sync_engine, v3)

    async def scenario() -> tuple[bool, Any]:
        engine = create_async_engine(db_url, connect_args={"options": "-c timezone=UTC"})
        reopened = asyncio.Event()
        release = asyncio.Event()

        async def first() -> Any:
            try:
                async with unit_of_work(engine) as uow:
                    done = await gaps.reopen_gap(
                        uow, owner, opp_id, gap["id"], GapReopening(reason="Back in scope"), '"1"'
                    )
                    reopened.set()
                    await release.wait()  # hold the lock, uncommitted
                    return done
            finally:
                reopened.set()  # never leave the other task waiting

        async def second() -> Any:
            await reopened.wait()
            async with unit_of_work(engine) as uow:
                return await estimates.set_baseline(
                    uow, owner, opp_id, UUID(v3), f'"{row_version}"'
                )

        try:
            t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
            await reopened.wait()
            await asyncio.sleep(0.5)
            second_blocked = not t2.done()
            release.set()
            return second_blocked, await asyncio.gather(t1, t2, return_exceptions=True)
        finally:
            await engine.dispose()

    second_blocked, (a, b) = run_async(scenario())

    assert not isinstance(a, BaseException), a
    assert second_blocked
    assert isinstance(b, BaselineBlockedError), b
    assert b.extensions is not None
    assert [x["kind"] for x in b.extensions["blockers"]] == ["gap"]
    assert _baselines(sync_engine, opp["id"]) == []


def test_a_newer_version_in_review_is_not_newer_approved(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [_, (_, pia)] = _approved(client, sync_engine)
    assert _set_now(client, sync_engine, headers, opp["id"], v3).status_code == 201
    v4 = _new_version(client, headers, opp["id"], v3)
    assert _submit(client, sync_engine, headers, opp["id"], v4).status_code == 200
    sent = _send(client, headers, opp["id"], v4, _row_version(sync_engine, v4), [pia], "pm")
    assert sent.status_code == 201, sent.text
    assert _status(sync_engine, v4) == "in_review"
    assert _gate(client, headers, opp["id"])["baseline_version"] == 3

    assert_problem(
        _set_now(client, sync_engine, headers, opp["id"], v4).json(), 409, "baseline_not_newer"
    )
    assert len(_baselines(sync_engine, opp["id"])) == 1
