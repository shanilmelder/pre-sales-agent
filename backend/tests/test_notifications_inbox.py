"""The Inbox (Story 9.2) against a real, migrated Postgres as psa_app: the spec's I/O matrix
(new request, cancelled, reminder, decided, back-fill, another user's item, empty), `notify`'s
idempotency, the reminder intervals and rerun, the grouping order and paging, marking read,
who has an Inbox, and the table grants.

People sign in through `/me`; Review Requests are sent through the API on directly inserted
Estimate Versions (`test_reviews_requests`). The live run-waiting and Conflict escalation
producers are covered in `test_workflows_decisions.py` and `test_conflicts_resolution.py`.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.notifications.application import public as notifications
from app.modules.notifications.application.public import NotificationKind
from app.modules.notifications.domain.notifications import (
    GROUP_ORDER,
    KIND_GROUP,
    SUMMARY_MAX,
    InboxGroup,
    clean_summary,
)
from app.modules.reviews.application import reminders
from app.modules.reviews.application.reminders import interval_number
from app.modules.workflows.adapters import repository as workflows_repo
from app.modules.workflows.application import runs as workflows_runs
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import REGISTRY, JobContext
from app.platform.uow import UnitOfWork, unit_of_work
from tests import test_opportunities as opportunity_tests
from tests.conftest import run_async
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import PSE, _create, _user
from tests.test_reviews_requests import (
    ENG,
    REASON,
    _assessment,
    _cancel,
    _send,
    _setup,
    _version,
)

client = opportunity_tests.client

INBOX = "/api/v1/inbox"
REMINDED = "reviews.review_request.reminded"


# --- domain (no DB) -------------------------------------------------------------------------


def test_every_kind_has_a_group_in_the_inbox_order() -> None:
    assert set(KIND_GROUP) == set(NotificationKind)
    assert GROUP_ORDER == (
        InboxGroup.REVIEWS,
        InboxGroup.CHALLENGES,
        InboxGroup.WAITING,
        InboxGroup.UPDATES,
    )
    assert KIND_GROUP[NotificationKind.REVIEW_REMINDER] == InboxGroup.REVIEWS
    assert KIND_GROUP[NotificationKind.CONFLICT_ESCALATED] == InboxGroup.WAITING
    assert KIND_GROUP[NotificationKind.REVIEW_CANCELLED] == InboxGroup.UPDATES


def test_summaries_are_one_line_and_cut_to_300_characters() -> None:
    assert clean_summary("  Review:\n Estimate v3  ") == "Review: Estimate v3"
    cut = clean_summary("x" * 400)
    assert len(cut) == SUMMARY_MAX
    assert cut.endswith("…")


def test_interval_number_counts_whole_intervals() -> None:
    day = 86_400
    assert interval_number(timedelta(days=2, hours=23), 3 * day) == 0
    assert interval_number(timedelta(days=3), 3 * day) == 1
    assert interval_number(timedelta(days=7), 3 * day) == 2


def test_the_reminder_job_and_setting() -> None:
    assert Settings().review_reminder_days == 3
    assert REGISTRY[reminders.SEND_REMINDERS].payload is reminders.SendReminders


# --- helpers --------------------------------------------------------------------------------


def _inbox(client: TestClient, headers: dict[str, str], page: int = 1) -> dict[str, Any]:
    resp = client.get(INBOX, headers=headers, params={"page": page})
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _unread(client: TestClient, headers: dict[str, str]) -> int:
    resp = client.get(f"{INBOX}/unread-count", headers=headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["unread"])


def _items(engine: Engine, recipient: UUID) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM notifications_notifications WHERE recipient_id = :r ORDER BY created_at, id",
        r=recipient,
    )


def _events(engine: Engine, opp_id: str, event_type: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :e "
        "ORDER BY occurred_at, id",
        o=opp_id,
        e=event_type,
    )


def _in_uow[T](db_url: str, work: Callable[[UnitOfWork], Awaitable[T]]) -> T:
    async def go() -> T:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await work(uow)
        finally:
            await engine.dispose()

    return run_async(go())


def _notify(db_url: str, recipient: UUID, key: str, **overrides: Any) -> bool:
    fields: dict[str, Any] = {
        "recipient_id": recipient,
        "kind": NotificationKind.REVIEW_CANCELLED,
        "opportunity_id": None,
        "subject_type": "reviews.review_request",
        "subject_id": uuid4(),
        "subject_version": 1,
        "summary": "Review cancelled: Estimate v1",
        "dedupe_key": key,
    }
    fields.update(overrides)
    return _in_uow(db_url, lambda uow: notifications.notify(uow, **fields))


def _remind(db_url: str, days: int = 3) -> int:
    return _in_uow(db_url, lambda uow: reminders.send_due_reminders(uow, days))


def _age(engine: Engine, request_id: str, days: float) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE reviews_review_requests SET created_at = now() - make_interval(secs => :s) "
                "WHERE id = :i"
            ),
            {"s": days * 86_400, "i": request_id},
        )


def _assessment_request(
    client: TestClient, engine: Engine, reviewer: UUID
) -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    """A second Opportunity: its owner, the Opportunity, and an engineering request to
    `reviewer` targeting its Security Assessment v2."""
    headers, owner = _user(client, engine, "Other Owner", PSE)
    opp = _create(client, headers)
    v1 = _version(engine, opp["id"], 1, created_by=owner)
    target = _assessment(engine, opp["id"], "security_agent", 2)
    sent = _send(
        client, headers, opp["id"], v1, 1, [reviewer], "engineering", [{"id": target, "version": 2}]
    )
    assert sent.status_code == 201, sent.text
    (request,) = sent.json()["items"]
    return owner, opp, request


# --- the matrix -----------------------------------------------------------------------------


def test_a_new_request_gives_each_reviewer_one_unread_item(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    ben_h, ben = _user(client, sync_engine, "Ben Reviewer", ENG)

    sent = _send(client, headers, opp["id"], v3, 1, [ana, ben])

    assert sent.status_code == 201, sent.text
    for reviewer_h, reviewer in ((ana_h, ana), (ben_h, ben)):
        (stored,) = _items(sync_engine, reviewer)
        assert (stored["kind"], stored["channel"], stored["read_at"]) == (
            "review_requested",
            "in_app",
            None,
        )
        assert _unread(client, reviewer_h) == 1
        body = _inbox(client, reviewer_h)
        assert (body["total"], body["unread"], body["page"], body["page_size"]) == (1, 1, 1, 25)
        (item,) = body["items"]
        request_id = stored["subject_id"]
        assert stored["dedupe_key"] == f"review:{request_id}:requested"
        assert item["summary"] == f"Review: Estimate v3 — {opp['title']}"
        assert (item["group"], item["read"], item["sender"]) == ("reviews", False, "Owner Person")
        assert (item["subject_status"], item["subject_status_label"], item["subject_open"]) == (
            "pending",
            "Pending",
            True,
        )
        assert item["href"] == f"/opportunities/{opp['id']}/estimate?review={request_id}"
        assert item["opportunity_title"] == opp["title"]
    assert _unread(client, headers) == 0  # the sender gets nothing


def test_cancelled_gives_an_update_and_the_review_item_shows_cancelled(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"]

    assert _cancel(client, headers, opp["id"], request).status_code == 200

    body = _inbox(client, ana_h)
    assert [i["kind"] for i in body["items"]] == ["review_requested", "review_cancelled"]
    review, update = body["items"]
    assert [review["group"], update["group"]] == ["reviews", "updates"]
    for item in body["items"]:
        assert (item["subject_status"], item["subject_status_label"]) == ("cancelled", "Cancelled")
        assert (item["subject_open"], item["href"]) == (False, None)
    assert update["summary"] == f"Review cancelled: Estimate v3 — {opp['title']}"
    assert REASON not in update["summary"]
    keys = {r["dedupe_key"] for r in _items(sync_engine, ana)}
    assert keys == {f"review:{request['id']}:requested", f"review:{request['id']}:cancelled"}
    assert _unread(client, ana_h) == 2


def test_one_reminder_per_interval_and_a_rerun_sends_nothing(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"]
    _age(sync_engine, request["id"], 7)
    # An Assessment-target request on a second Opportunity: labels across Opportunities.
    _, other_opp, assessment = _assessment_request(client, sync_engine, ana)
    _age(sync_engine, assessment["id"], 7)
    requested = next(
        i
        for i in _inbox(client, ana_h)["items"]
        if i["subject_id"] == assessment["id"] and i["kind"] == "review_requested"
    )
    assert requested["summary"] == f"Review: Security Assessment v2 — {other_opp['title']}"

    _remind(db_url)

    reminder_rows = [r for r in _items(sync_engine, ana) if r["kind"] == "review_reminder"]
    assert sorted(r["dedupe_key"] for r in reminder_rows) == sorted(
        [f"review:{request['id']}:reminder:2", f"review:{assessment['id']}:reminder:2"]
    )
    (other_reminder,) = [r for r in reminder_rows if str(r["subject_id"]) == assessment["id"]]
    assert other_reminder["summary"] == (
        f"Reminder: review Security Assessment v2 — {other_opp['title']}"
    )
    assert len(_events(sync_engine, other_opp["id"], REMINDED)) == 1
    (event,) = _events(sync_engine, opp["id"], REMINDED)
    assert event["payload"] == {
        "request_id": request["id"],
        "reviewer_id": str(ana),
        "interval_number": 2,
    }
    assert (event["actor_type"], event["actor_id"]) == ("system", "reviews.send_reminders")
    (reminder,) = [
        i
        for i in _inbox(client, ana_h)["items"]
        if i["kind"] == "review_reminder" and i["subject_id"] == request["id"]
    ]
    assert reminder["summary"] == f"Reminder: review Estimate v3 — {opp['title']}"
    assert reminder["group"] == "reviews"

    _remind(db_url)  # the same day: nothing more

    assert len([r for r in _items(sync_engine, ana) if r["kind"] == "review_reminder"]) == 2
    assert len(_events(sync_engine, opp["id"], REMINDED)) == 1

    _age(sync_engine, request["id"], 9)  # the third interval
    _remind(db_url)
    assert len(_events(sync_engine, opp["id"], REMINDED)) == 2


def test_a_young_request_gets_no_reminder(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"]
    _age(sync_engine, request["id"], 2.9)

    _remind(db_url)

    assert _events(sync_engine, opp["id"], REMINDED) == []


def test_the_job_handler_uses_the_reminder_days_setting(
    client: TestClient, sync_engine: Engine, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"]
    _age(sync_engine, request["id"], 1.1)
    monkeypatch.setattr(reminders, "reminder_settings", lambda: Settings(review_reminder_days=1))

    async def handle() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=uuid4(),
            job_type=reminders.SEND_REMINDERS,
            attempt=1,
            max_attempts=3,
            opportunity_id=None,
            engine=engine,
        )
        try:
            await reminders.send_reminders(ctx, reminders.SendReminders())
        finally:
            await engine.dispose()

    run_async(handle())

    (row,) = [r for r in _items(sync_engine, ana) if r["kind"] == "review_reminder"]
    assert row["dedupe_key"] == f"review:{request['id']}:reminder:1"
    (event,) = _events(sync_engine, opp["id"], REMINDED)
    assert event["payload"]["interval_number"] == 1


def test_superseded_and_cancelled_requests_get_no_reminder(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    _, ben = _user(client, sync_engine, "Ben Reviewer", ENG)
    first, second = _send(client, headers, opp["id"], v3, 1, [ana, ben]).json()["items"]
    assert _cancel(client, headers, opp["id"], first).status_code == 200
    with sync_engine.begin() as conn:  # 9.4 supersedes; here the status is set directly
        conn.execute(
            sa.text("UPDATE reviews_review_requests SET status = 'superseded' WHERE id = :i"),
            {"i": second["id"]},
        )
    _age(sync_engine, first["id"], 7)
    _age(sync_engine, second["id"], 7)

    _remind(db_url)

    assert _events(sync_engine, opp["id"], REMINDED) == []
    assert not [r for r in _items(sync_engine, ben) if r["kind"] == "review_reminder"]


def test_another_users_item_is_404_and_unchanged(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    _send(client, headers, opp["id"], v3, 1, [ana])
    (stored,) = _items(sync_engine, ana)

    for path in (f"{INBOX}/{stored['id']}/read", f"{INBOX}/{uuid4()}/read"):
        resp = client.post(path, headers=headers)
        assert resp.status_code == 404
        assert_problem(resp.json(), 404, "not_found")
    assert client.post(f"{INBOX}/read-all", headers=headers).json()["marked"] == 0
    (after,) = _items(sync_engine, ana)
    assert after["read_at"] is None
    assert client.post(f"{INBOX}/not-a-uuid/read", headers=headers).status_code == 422


def test_an_empty_inbox(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "New Person", "commercial")
    assert _inbox(client, headers) == {
        "items": [],
        "page": 1,
        "page_size": 25,
        "total": 0,
        "unread": 0,
    }
    assert _unread(client, headers) == 0


# --- reading and marking --------------------------------------------------------------------


def test_marking_one_then_all_read(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (first,) = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"]
    other = _create(client, headers)
    v1 = _version(sync_engine, other["id"], 1)
    _send(client, headers, other["id"], v1, 1, [ana])
    assert _unread(client, ana_h) == 2
    item_id = next(r["id"] for r in _items(sync_engine, ana) if str(r["subject_id"]) == first["id"])

    marked = client.post(f"{INBOX}/{item_id}/read", headers=ana_h)

    assert marked.status_code == 200, marked.text
    assert (marked.json()["id"], marked.json()["read"]) == (str(item_id), True)
    assert _unread(client, ana_h) == 1
    (read_at,) = [r["read_at"] for r in _items(sync_engine, ana) if r["id"] == item_id]
    again = client.post(f"{INBOX}/{item_id}/read", headers=ana_h)
    assert again.status_code == 200
    (still,) = [r["read_at"] for r in _items(sync_engine, ana) if r["id"] == item_id]
    assert still == read_at  # read once, kept

    all_read = client.post(f"{INBOX}/read-all", headers=ana_h)
    assert all_read.json() == {"marked": 1, "unread": 0}
    assert [i["read"] for i in _inbox(client, ana_h)["items"]] == [True, True]


def test_groups_come_in_order_then_newest_first_25_a_page(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, me = _user(client, sync_engine, "Busy Person", ENG)
    kinds = [
        NotificationKind.REVIEW_CANCELLED,
        NotificationKind.RUN_WAITING,
        NotificationKind.REVIEW_REQUESTED,
        NotificationKind.CONFLICT_ESCALATED,
        NotificationKind.REVIEW_REMINDER,
    ]
    for n in range(30):
        kind = kinds[n % len(kinds)]
        subject = {
            NotificationKind.RUN_WAITING: "workflows.decision",
            NotificationKind.CONFLICT_ESCALATED: "conflicts.conflict",
        }.get(kind, "reviews.review_request")
        assert _notify(db_url, me, f"test:{uuid4()}", kind=kind, subject_type=subject)

    first = _inbox(client, headers)
    second = _inbox(client, headers, 2)

    assert (first["total"], len(first["items"]), len(second["items"])) == (30, 25, 5)
    listed = first["items"] + second["items"]
    ranks = [GROUP_ORDER.index(InboxGroup(i["group"])) for i in listed]
    assert ranks == sorted(ranks)
    for group in ("reviews", "waiting", "updates"):
        times = [i["created_at"] for i in listed if i["group"] == group]
        assert times == sorted(times, reverse=True)
    unknown = [i for i in listed if i["subject_status"] is None]
    assert len(unknown) == 30  # their subjects don't exist: no status and no link
    assert {i["href"] for i in unknown} == {None}
    assert _inbox(client, headers, 3)["items"] == []


def test_notify_is_idempotent_by_dedupe_key(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    _, me = _user(client, sync_engine, "Idem Person", ENG)
    key = f"test:{uuid4()}"
    assert _notify(db_url, me, key) is True
    assert _notify(db_url, me, key, summary="Something else") is False
    (stored,) = _items(sync_engine, me)
    assert stored["summary"] == "Review cancelled: Estimate v1"
    long = _notify(db_url, me, f"test:{uuid4()}", summary="y" * 500)
    assert long is True
    assert max(len(r["summary"]) for r in _items(sync_engine, me)) == SUMMARY_MAX


def test_only_a_user_holding_a_role_has_an_inbox(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "No Role Person")
    resp = client.get(INBOX, headers=headers)
    assert resp.status_code == 403
    assert_problem(resp.json(), 403, "forbidden")
    assert client.get(INBOX).status_code == 401


def test_psa_app_cannot_delete_items(client: TestClient, sync_engine: Engine, db_url: str) -> None:
    _, me = _user(client, sync_engine, "Grant Person", ENG)
    _notify(db_url, me, f"test:{uuid4()}")
    with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM notifications_notifications WHERE recipient_id = :r"),
                {"r": me},
            )
    (schedule,) = rows(
        sync_engine,
        "SELECT job_type, interval_s FROM platform_schedules WHERE name = :n",
        n=reminders.SEND_REMINDERS,
    )
    assert schedule == {"job_type": "reviews.send_reminders", "interval_s": 86_400}


# --- back-fill ------------------------------------------------------------------------------


def _waiting_run(engine: Engine, opp_id: str, starter: UUID | None) -> tuple[UUID, UUID]:
    """A run waiting on an open decision about the Security Agent, started by `starter` (the
    system when None, as after a Gap detection): (run id, decision id)."""
    run_id, task_id, decision_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO workflows_runs (id, opportunity_id, status) "
                "VALUES (:id, :o, 'waiting_for_human')"
            ),
            {"id": run_id, "o": opp_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO workflows_tasks (id, run_id, agent, status, config_version_id) "
                "SELECT :id, :run, 'security_agent', 'queued', id "
                "FROM registry_agent_config_versions WHERE agent_id = 'security_agent' "
                "ORDER BY version LIMIT 1"
            ),
            {"id": task_id, "run": run_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO workflows_plan_versions (id, run_id, version, tasks, "
                "created_by_type, created_by) VALUES (:id, :run, 1, '[]', :type, :by)"
            ),
            {
                "id": uuid4(),
                "run": run_id,
                "type": "system" if starter is None else "user",
                "by": "workflows.execute" if starter is None else str(starter),
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO workflows_decisions (id, run_id, task_id, kind, status) "
                "VALUES (:id, :run, :task, 'plan_escalation', 'open')"
            ),
            {"id": decision_id, "run": run_id, "task": task_id},
        )
    return run_id, decision_id


def test_a_system_started_waiting_run_notifies_the_owner(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, owner = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    run_id, decision = _waiting_run(sync_engine, opp["id"], None)

    async def wait(uow: UnitOfWork) -> None:
        run = await workflows_repo.get_run(uow, run_id)
        assert run is not None
        (task,) = await workflows_repo.tasks_of(uow, run_id)
        await workflows_runs._waiting_on(uow, run, decision, task)

    _in_uow(db_url, wait)

    (item,) = _items(sync_engine, owner)
    assert (item["kind"], item["dedupe_key"]) == ("run_waiting", f"decision:{decision}")


def _escalated_conflict(engine: Engine, opp_id: str, reviewer: UUID, by: UUID) -> UUID:
    conflict_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conflicts_conflicts (id, opportunity_id, run_id, type, severity, "
                "status, detected_by, fingerprint, summary, detection_pass, escalated_to, "
                "escalated_by, escalated_at, escalation_reason, row_version) VALUES (:id, :o, "
                ":run, 'effort', 'high', 'escalated', 'rule', :fp, 'Agents disagree', 1, :to, "
                ":by, :at, 'Needs a call', 2)"
            ),
            {
                "id": conflict_id,
                "o": opp_id,
                "run": uuid4(),
                "fp": uuid4().hex,
                "to": reviewer,
                "by": by,
                "at": datetime.now(UTC) - timedelta(days=1),
            },
        )
    return conflict_id


def test_the_migration_backfills_open_state_and_a_live_insert_is_a_no_op(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, owner, opp, v3 = _setup(client, sync_engine)
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    sam_h, sam = _user(client, sync_engine, "Sam Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"]
    _, decision = _waiting_run(sync_engine, opp["id"], owner)
    conflict = _escalated_conflict(sync_engine, opp["id"], sam, owner)
    # A second Opportunity: an Assessment-target request, and a run the system queued.
    other_owner, other_opp, assessment = _assessment_request(client, sync_engine, ana)
    _, system_decision = _waiting_run(sync_engine, other_opp["id"], None)
    # A third, with a messy title and a run a collaborator started: theirs, not the owner's.
    third_h, third_owner = _user(client, sync_engine, "Third Owner", PSE)
    third = _create(client, third_h)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE opportunities_opportunities SET title = :t WHERE id = :i"),
            {"t": "  A\n  B ", "i": third["id"]},
        )
    _, cara = _user(client, sync_engine, "Cara Collaborator", PSE)
    _, cara_decision = _waiting_run(sync_engine, third["id"], cara)
    (escalated_at,) = [
        r["escalated_at"]
        for r in rows(
            sync_engine, "SELECT escalated_at FROM conflicts_conflicts WHERE id = :i", i=conflict
        )
    ]

    _alembic("downgrade", "0047_reviews_review_requests")
    try:
        assert rows(
            sync_engine,
            "SELECT to_regclass('notifications_notifications') AS t",
        ) == [{"t": None}]
    finally:
        _alembic("upgrade", "head")

    review, other_review = sorted(
        _items(sync_engine, ana), key=lambda r: str(r["subject_id"]) != request["id"]
    )
    assert other_review["dedupe_key"] == f"review:{assessment['id']}:requested"
    assert other_review["summary"] == (f"Review: Security Assessment v2 — {other_opp['title']}")
    (cara_waiting,) = _items(sync_engine, cara)
    assert cara_waiting["dedupe_key"] == f"decision:{cara_decision}"
    assert cara_waiting["summary"].endswith("— A B")
    assert _items(sync_engine, third_owner) == []
    (system_waiting,) = _items(sync_engine, other_owner)
    assert (system_waiting["kind"], system_waiting["dedupe_key"]) == (
        "run_waiting",
        f"decision:{system_decision}",
    )
    assert (review["kind"], review["dedupe_key"], review["subject_id"]) == (
        "review_requested",
        f"review:{request['id']}:requested",
        UUID(request["id"]),
    )
    assert review["summary"] == f"Review: Estimate v3 — {opp['title']}"
    (waiting,) = _items(sync_engine, owner)
    assert (waiting["kind"], waiting["dedupe_key"], waiting["subject_type"]) == (
        "run_waiting",
        f"decision:{decision}",
        "workflows.decision",
    )
    assert waiting["summary"] == f"Decision needed: Security Agent is not active — {opp['title']}"
    (escalation,) = _items(sync_engine, sam)
    epoch = int(escalated_at.timestamp())
    assert (escalation["kind"], escalation["dedupe_key"]) == (
        "conflict_escalated",
        f"conflict:{conflict}:escalated:{epoch}",
    )
    assert escalation["summary"] == f"Conflict escalated: Effort Conflict — {opp['title']}"

    # The live producers' keys: nothing more is written.
    assert _notify(db_url, ana, f"review:{request['id']}:requested") is False
    assert _notify(db_url, owner, f"decision:{decision}") is False
    assert _notify(db_url, sam, f"conflict:{conflict}:escalated:{epoch}") is False

    # Each item reads its subject's status live.
    owner_item = _inbox(client, headers)["items"][0]
    assert (owner_item["group"], owner_item["subject_status_label"]) == ("waiting", "Waiting")
    assert owner_item["href"] == f"/opportunities/{opp['id']}/assessments"
    sam_item = _inbox(client, sam_h)["items"][0]
    assert (sam_item["subject_status"], sam_item["href"]) == (
        "escalated",
        f"/opportunities/{opp['id']}/conflicts",
    )
    assert _inbox(client, ana_h)["items"][0]["subject_open"] is True
