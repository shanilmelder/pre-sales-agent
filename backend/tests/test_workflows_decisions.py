"""Pause and resume (Story 5.5) against a real, migrated Postgres as psa_app: a task whose
Agent is disabled asks a person instead of being skipped. Its node records a
`plan_escalation` decision and interrupts the graph, the run waits (`waiting_for_human`),
and resolving the decision (Continue without, or Re-plan once the Agent is active again)
resumes the checkpointed graph from the interrupted node with `Command(resume=…)`.

Every row of the spec's I/O matrix: escalate, idempotent re-run, Continue without, Re-plan,
restart (a fresh runner and pool), concurrent resolves, cancel while waiting, coalescing,
who may resolve and the plan history; also the grants, and the migration's downgrade and
backfill. The specialist Agents answer through the fake per-agent gateway of
`test_assessments_specialists.py`.
"""

import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.workflows.application import public as workflows_public
from app.modules.workflows.application import runs as workflows_runs
from app.orchestration.runner import LangGraphRunner
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.uow import unit_of_work
from tests import conftest
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_assessments_specialists import (
    AgentGateway,
    assessment_rows,
    cancel,
    install,
    prepared,
    replies,
    retry,
    run_rows,
    start,
    started,
    task_rows,
)
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import ASSESS, BASE, RESUME, FakeGateway, drain
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import PSE, _add, _user
from tests.test_role_admin import _admin

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run

REGISTRY = "/api/v1/registry/agents"
SECURITY = "security_agent"
AGENTS = ("engineering_agent", "pm_agent", SECURITY)
TOUCHED = ("engineering_agent", "pm_agent", SECURITY)


@pytest.fixture
def restore_agents(sync_engine: Engine) -> Iterator[None]:
    """Put the specialist Agents back to `active` after the test (the registry is shared)."""
    yield
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE registry_agents SET status = 'active', row_version = row_version + 1 "
                "WHERE agent_id = ANY(:ids) AND status <> 'active'"
            ),
            {"ids": list(TOUCHED)},
        )


# --- helpers --------------------------------------------------------------------------------


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def set_status(client: TestClient, admin: dict[str, str], agent: str, status: str) -> None:
    current = client.get(f"{REGISTRY}/{agent}", headers=admin)
    assert current.status_code == 200, current.text
    resp = client.post(
        f"{REGISTRY}/{agent}/status",
        headers={**admin, **if_match(current.json()["row_version"])},
        json={"status": status},
    )
    assert resp.status_code == 200, resp.text


def new_config_version(client: TestClient, admin: dict[str, str], agent: str) -> UUID:
    """A new current config version of the Agent, equal to its current one apart from its
    id and version."""
    current = client.get(f"{REGISTRY}/{agent}", headers=admin).json()
    same = {
        key: current["current_config"][key]
        for key in (
            "semver",
            "model_profile",
            "prompt_version",
            "input_schema_version",
            "output_schema_version",
            "tool_permissions",
            "budgets",
        )
    }
    created = client.post(
        f"{REGISTRY}/{agent}/config-versions",
        headers={**admin, **if_match(current["row_version"])},
        json=same,
    )
    assert created.status_code == 201, created.text
    return UUID(created.json()["current_config"]["id"])


def resolve(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    run_id: str,
    decision_id: str,
    choice: str,
    version: int | None = 1,
) -> Any:
    extra = {} if version is None else if_match(version)
    return client.post(
        f"{BASE}/{opp_id}/assessment-runs/{run_id}/decisions/{decision_id}/resolve",
        headers={**headers, **extra},
        json={"choice": choice},
    )


def view(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{opp_id}/assessments", headers=headers)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def decision_rows(engine: Engine, run_id: Any) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM workflows_decisions WHERE run_id = :r", r=run_id)


def plan_rows(engine: Engine, run_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine, "SELECT * FROM workflows_plan_versions WHERE run_id = :r ORDER BY version", r=run_id
    )


def trace_rows(engine: Engine, opp_id: str, event_type: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :e "
        "ORDER BY occurred_at, id",
        o=opp_id,
        e=event_type,
    )


def progress(engine: Engine, run_id: Any) -> list[tuple[str, str]]:
    return [
        (r["event_type"], r["summary"])
        for r in rows(
            engine, "SELECT * FROM workflows_progress WHERE run_id = :r ORDER BY id", r=run_id
        )
    ]


def problem(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body: dict[str, Any] = resp.json()
    assert_problem(body, status, code)
    return body


def waiting(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    *,
    disable: str = "disabled",
) -> tuple[dict[str, str], dict[str, str], dict[str, Any], dict[str, Any], AgentGateway]:
    """An Opportunity whose run waits on the Security Agent (disabled before the start):
    (owner headers, admin headers, Opportunity, run as started, fake gateway)."""
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    set_status(client, admin, SECURITY, disable)
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]  # the job ends without error
    return headers, admin, opp, body, fake


# --- escalate -------------------------------------------------------------------------------


def test_a_disabled_agent_escalates_and_the_run_waits_for_a_person(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, _, opp, body, fake = waiting(client, sync_engine, db_url, gateway)

    # Every task was queued and pinned, the disabled Agent's too: nothing is skipped.
    assert [t["status"] for t in body["tasks"]] == ["queued"] * 4  # with the Critic's (6.4)
    assert [t["skip_reason"] for t in body["tasks"]] == [None] * 4
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "waiting_for_human"
    assert run["finished_at"] is None
    tasks = task_rows(sync_engine, run["id"])
    assert {a: tasks[a]["status"] for a in AGENTS} == {
        "engineering_agent": "succeeded",
        "pm_agent": "succeeded",
        SECURITY: "queued",
    }
    assert tasks["critic_agent"]["status"] == "queued"  # it waits for every specialist
    assert (tasks[SECURITY]["started_at"], tasks[SECURITY]["skip_reason"]) == (None, None)
    assert {r.caller.agent_id for r in fake.requests} == {"engineering_agent", "pm_agent"}

    (decision,) = decision_rows(sync_engine, run["id"])
    assert (decision["kind"], decision["status"], decision["choice"]) == (
        "plan_escalation",
        "open",
        None,
    )
    assert (decision["task_id"], decision["row_version"]) == (tasks[SECURITY]["id"], 1)
    assert decision["payload"] == {  # ids and codes only
        "decision_id": str(decision["id"]),
        "kind": "plan_escalation",
        "run_id": str(run["id"]),
        "task_id": str(tasks[SECURITY]["id"]),
        "agent": SECURITY,
        "choices": ["continue_without", "replan"],
    }
    (event,) = trace_rows(sync_engine, opp["id"], "workflows.run.waiting_for_human")
    assert (event["actor_type"], event["actor_id"]) == ("system", "workflows.execute")
    assert (event["subject_type"], event["subject_id"]) == ("assessments.assessment_run", run["id"])
    assert event["payload"] == {
        "decision_id": str(decision["id"]),
        "task_id": str(tasks[SECURITY]["id"]),
        "agent": SECURITY,
        "kind": "plan_escalation",
    }
    assert trace_rows(sync_engine, opp["id"], "assessments.task.skipped") == []
    assert progress(sync_engine, run["id"])[-1] == (
        "workflows.run.waiting_for_human",
        "security_agent waiting_for_human",
    )

    shown = view(client, headers, opp["id"])
    assert shown["can_resolve"] is True
    assert (shown["run"]["status"], shown["run"]["plan_version"]) == ("waiting_for_human", 1)
    (open_decision,) = shown["run"]["decisions"]
    assert open_decision == {
        "id": str(decision["id"]),
        "kind": "plan_escalation",
        "agent": SECURITY,
        "agent_name": "Security Agent",
        "agent_active": False,
        "status": "open",
        "choice": None,
        "row_version": 1,
        "created_at": open_decision["created_at"],
        "resolved_by": None,
        "resolved_at": None,
    }
    (plan,) = shown["run"]["plan_versions"]
    assert (plan["version"], plan["created_by"]) == (1, "Owner Person")
    assert {t["agent"]: t["config_version_id"] for t in plan["tasks"]} == {
        a: str(tasks[a]["config_version_id"]) for a in (*AGENTS, "critic_agent")
    }

    # The Estimate tab's "run in progress" is queued/running only.
    async def in_progress() -> bool:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await workflows_public.run_in_progress(uow, UUID(opp["id"]))
        finally:
            await engine.dispose()

    assert run_async(in_progress()) is False


def test_a_node_run_again_before_the_resolve_keeps_one_decision_and_one_event(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The worker dies after the node recorded the decision but before the run was marked
    waiting: the job runs again, the node interrupts again, and nothing is recorded twice."""
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    set_status(client, admin, SECURITY, "disabled")
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    real_wait = workflows_runs._wait
    calls: list[int] = []

    async def dies_once(ctx: Any, run_id: UUID, opportunity_id: UUID) -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the worker died")
        return await real_wait(ctx, run_id, opportunity_id)

    monkeypatch.setattr(workflows_runs, "_wait", dies_once)
    with caplog.at_level(logging.INFO):
        assert drain(db_url, ASSESS) == ["failed_retrying", "succeeded"]

    assert run_rows(sync_engine, opp["id"])[0]["status"] == "waiting_for_human"
    assert len(decision_rows(sync_engine, body["id"])) == 1
    assert len(trace_rows(sync_engine, opp["id"], "workflows.run.waiting_for_human")) == 1
    assert (fake.calls("engineering_agent"), fake.calls("pm_agent")) == (1, 1)
    escalated = [r for r in caplog.records if r.getMessage() == "orchestration.task_escalated"]
    assert len(escalated) == 2  # the node interrupted on both attempts
    assert "orchestration.run_resumed" in [r.getMessage() for r in caplog.records]


# --- continue without -----------------------------------------------------------------------


def test_continue_without_skips_the_task_and_finishes_without_rerunning_the_others(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, _, opp, body, fake = waiting(client, sync_engine, db_url, gateway)
    (decision,) = view(client, headers, opp["id"])["run"]["decisions"]

    resolved = resolve(client, headers, opp["id"], body["id"], decision["id"], "continue_without")

    assert resolved.status_code == 200, resolved.text
    assert resolved.headers["ETag"] == '"2"'
    run = resolved.json()
    assert run["status"] == "queued"
    (after,) = run["decisions"]
    assert (after["status"], after["choice"], after["row_version"]) == (
        "resolved",
        "continue_without",
        2,
    )
    assert after["resolved_by"] == "Owner Person"
    assert run["plan_version"] == 1  # Continue without changes no plan
    (event,) = trace_rows(sync_engine, opp["id"], "workflows.decision.resolved")
    assert event["actor_type"] == "user"
    assert event["payload"]["choice"] == "continue_without"
    assert event["payload"]["plan_version"] == 1
    (job,) = rows(
        sync_engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
        t=RESUME,
        o=opp["id"],
    )
    assert job["payload"] == {"run_id": body["id"]}

    assert drain(db_url, ASSESS, RESUME) == ["succeeded"]

    tasks = task_rows(sync_engine, body["id"])
    assert (tasks[SECURITY]["status"], tasks[SECURITY]["skip_reason"]) == (
        "skipped",
        "agent_disabled",
    )
    assert tasks[SECURITY]["started_at"] is None
    (finished,) = run_rows(sync_engine, opp["id"])
    # A person chose to continue without the Agent: that skip doesn't count against the run
    # (user decision, 2026-10-24).
    assert finished["status"] == "succeeded"
    assert finished["finished_at"] is not None
    assert (fake.calls("engineering_agent"), fake.calls("pm_agent"), fake.calls(SECURITY)) == (
        1,
        1,
        0,
    )
    for agent in ("engineering_agent", "pm_agent"):  # not re-run: one Assessment each
        assert len(assessment_rows(sync_engine, opp["id"], agent)) == 1
    (skipped,) = trace_rows(sync_engine, opp["id"], "assessments.task.skipped")
    assert (skipped["actor_type"], skipped["payload"]["agent"]) == ("system", SECURITY)
    estimates = rows(
        sync_engine,
        "SELECT * FROM estimates_estimate_versions WHERE source_run_id = :r",
        r=body["id"],
    )
    assert len(estimates) == 1  # the Estimate is built from the Assessments
    shown = view(client, headers, opp["id"])["run"]
    (security,) = [t for t in shown["tasks"] if t["agent"] == SECURITY]
    assert security["skip_reason"] == "agent_disabled"
    assert shown["status"] == "succeeded"
    assert progress(sync_engine, body["id"])[-1] == ("workflows.run.ended", "run succeeded")
    (completed,) = trace_rows(sync_engine, opp["id"], "assessments.assessment_run.completed")
    assert completed["payload"] == {
        "status": "succeeded",
        "task_count": 4,  # the three specialists and the Critic (Story 6.4)
        "succeeded_count": 3,
        "failed_count": 0,  # the chosen skip is not a failure
    }


# --- re-plan --------------------------------------------------------------------------------


def test_replan_is_409_while_the_agent_is_disabled_then_repins_and_runs_the_task(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, admin, opp, body, fake = waiting(client, sync_engine, db_url, gateway)
    (decision,) = view(client, headers, opp["id"])["run"]["decisions"]
    pinned = task_rows(sync_engine, body["id"])[SECURITY]["config_version_id"]

    refused = resolve(client, headers, opp["id"], body["id"], decision["id"], "replan")
    assert problem(refused, 409, "registry_agent_disabled")["detail"] == (
        "Security Agent is disabled"
    )
    assert decision_rows(sync_engine, body["id"])[0]["status"] == "open"  # nothing written

    newer = new_config_version(client, admin, SECURITY)
    assert newer != pinned
    set_status(client, admin, SECURITY, "active")
    shown = view(client, headers, opp["id"])["run"]
    assert shown["decisions"][0]["agent_active"] is True

    resolved = resolve(client, headers, opp["id"], body["id"], decision["id"], "replan")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["plan_version"] == 2
    assert task_rows(sync_engine, body["id"])[SECURITY]["config_version_id"] == newer
    assert run_rows(sync_engine, opp["id"])[0]["plan_version"] == 2

    assert drain(db_url, ASSESS, RESUME) == ["succeeded"]

    tasks = task_rows(sync_engine, body["id"])
    assert {tasks[a]["status"] for a in AGENTS} == {"succeeded"}
    assert run_rows(sync_engine, opp["id"])[0]["status"] == "succeeded"
    assert (fake.calls("engineering_agent"), fake.calls("pm_agent"), fake.calls(SECURITY)) == (
        1,
        1,
        1,
    )
    (call,) = [r for r in fake.requests if r.caller.agent_id == SECURITY]
    assert call.caller.config_version == str(newer)
    (stored,) = assessment_rows(sync_engine, opp["id"], SECURITY)
    assert stored["config_version_id"] == newer

    # Plan history: v1 with the old pin, v2 re-pinned, each with who and when.
    plans = plan_rows(sync_engine, body["id"])
    assert [p["version"] for p in plans] == [1, 2]
    by_agent = [{t["agent"]: t["config_version_id"] for t in p["tasks"]} for p in plans]
    assert by_agent[0][SECURITY] == str(pinned)
    assert by_agent[1][SECURITY] == str(newer)
    assert by_agent[0]["pm_agent"] == by_agent[1]["pm_agent"]
    assert [p["created_by_type"] for p in plans] == ["user", "user"]
    history = view(client, headers, opp["id"])["run"]["plan_versions"]
    assert [(p["version"], p["created_by"]) for p in history] == [
        (1, "Owner Person"),
        (2, "Owner Person"),
    ]
    security_pins = [
        next(t for t in p["tasks"] if t["agent"] == SECURITY)["config_version_id"] for p in history
    ]
    assert security_pins == [str(pinned), str(newer)]
    assert history[0]["created_at"] <= history[1]["created_at"]
    (event,) = trace_rows(sync_engine, opp["id"], "workflows.decision.resolved")
    assert (event["payload"]["choice"], event["payload"]["plan_version"]) == ("replan", 2)


# --- restart --------------------------------------------------------------------------------


def test_a_waiting_run_resumes_from_its_checkpoint_with_a_fresh_runner_and_pool(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, _, opp, body, fake = waiting(client, sync_engine, db_url, gateway)
    # The worker restarts: its runner and checkpointer pool are gone; a new one starts.
    workflows_public.install_runner(None)
    fresh = LangGraphRunner(lambda: conftest._checkpointer_per_call(db_url))
    workflows_public.install_runner(fresh)
    (decision,) = view(client, headers, opp["id"])["run"]["decisions"]
    resolved = resolve(client, headers, opp["id"], body["id"], decision["id"], "continue_without")
    assert resolved.status_code == 200, resolved.text

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert drain(db_url, RESUME) == ["succeeded"]

    (resumed,) = [r for r in caplog.records if r.getMessage() == "orchestration.run_resumed"]
    assert getattr(resumed, "resumed_count", None) == 1  # Command(resume=…) from the checkpoint
    entered = {
        getattr(r, "task_id", None)
        for r in caplog.records
        if r.getMessage() == "orchestration.node_entered"
    }
    tasks = task_rows(sync_engine, body["id"])
    # Security's node resumes; the Critic's (Story 6.4) runs once Security has ended.
    assert entered == {str(tasks[SECURITY]["id"]), str(tasks["critic_agent"]["id"])}
    assert (fake.calls("engineering_agent"), fake.calls("pm_agent")) == (1, 1)
    for agent in ("engineering_agent", "pm_agent"):  # no duplicate Assessments
        assert len(assessment_rows(sync_engine, opp["id"], agent)) == 1
    assert task_rows(sync_engine, body["id"])[SECURITY]["status"] == "skipped"
    assert run_rows(sync_engine, opp["id"])[0]["status"] == "succeeded"


# --- race -----------------------------------------------------------------------------------


def test_two_resolves_with_the_same_if_match_apply_only_the_first(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, _, opp, body, _ = waiting(client, sync_engine, db_url, gateway)
    colleague, colleague_id = _user(client, sync_engine, "Colleague Person", PSE)
    assert _add(client, headers, opp, colleague_id).status_code == 200
    (decision,) = view(client, headers, opp["id"])["run"]["decisions"]

    first = resolve(client, headers, opp["id"], body["id"], decision["id"], "continue_without")
    second = resolve(client, colleague, opp["id"], body["id"], decision["id"], "replan")

    assert first.status_code == 200, first.text
    assert problem(second, 412, "row_version_mismatch")["detail"] == (
        "Already resolved by Owner Person."
    )
    (row,) = decision_rows(sync_engine, body["id"])
    assert (row["choice"], row["row_version"]) == ("continue_without", 2)
    assert len(trace_rows(sync_engine, opp["id"], "workflows.decision.resolved")) == 1
    # The current version on a resolved decision: not open.
    late = resolve(client, colleague, opp["id"], body["id"], decision["id"], "replan", 2)
    problem(late, 409, "decision_not_open")
    problem(
        resolve(client, headers, opp["id"], body["id"], decision["id"], "replan", None),
        428,
        "if_match_required",
    )


# --- cancel while waiting -------------------------------------------------------------------


def test_cancelling_a_waiting_run_cancels_its_decision(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, _, opp, body, _ = waiting(client, sync_engine, db_url, gateway)
    (decision,) = view(client, headers, opp["id"])["run"]["decisions"]

    cancelled = cancel(client, headers, opp["id"], body["id"])

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    tasks = task_rows(sync_engine, body["id"])
    assert (tasks[SECURITY]["status"], tasks[SECURITY]["skip_reason"]) == ("skipped", None)
    assert decision_rows(sync_engine, body["id"])[0]["status"] == "cancelled"
    assert cancelled.json()["decisions"][0]["status"] == "cancelled"
    refused = resolve(client, headers, opp["id"], body["id"], decision["id"], "continue_without")
    problem(refused, 409, "decision_not_open")
    assert (
        rows(
            sync_engine,
            "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
            t=RESUME,
            o=opp["id"],
        )
        == []
    )
    # A new run can start.
    assert start(client, headers, opp["id"]).status_code == 201


# --- coalesce -------------------------------------------------------------------------------


def test_a_waiting_run_is_active_coalesces_and_is_never_stale(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, _, opp, body, _ = waiting(client, sync_engine, db_url, gateway)
    with sync_engine.begin() as conn:  # waiting for days: still not lost
        conn.execute(
            sa.text("UPDATE workflows_runs SET queued_at = now() - :age WHERE id = :r"),
            {"age": workflows_runs.stale_after() * 10, "r": body["id"]},
        )

    async def enqueue() -> UUID:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await workflows_runs.enqueue_run(uow, UUID(opp["id"]))
        finally:
            await engine.dispose()

    assert str(run_async(enqueue())) == body["id"]  # a Gap detection adds no run
    problem(start(client, headers, opp["id"]), 409, "assessment_in_progress")
    problem(retry(client, headers, opp["id"], body["id"], SECURITY), 409, "assessment_in_progress")
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "waiting_for_human"
    assert view(client, headers, opp["id"])["run"]["status"] == "waiting_for_human"
    assert task_rows(sync_engine, body["id"])[SECURITY]["status"] == "queued"


# --- who ------------------------------------------------------------------------------------


def test_only_the_owner_and_collaborators_except_sales_reps_resolve(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    headers, _, opp, body, _ = waiting(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    (decision,) = view(client, headers, opp["id"])["run"]["decisions"]

    rep_view = view(client, rep, opp["id"])
    assert (rep_view["can_resolve"], rep_view["can_start"]) == (False, False)
    for who, status, code in ((rep, 403, "forbidden"), (reader, 403, "forbidden")):
        resp = resolve(client, who, opp["id"], body["id"], decision["id"], "continue_without")
        problem(resp, status, code)
    resp = resolve(client, outsider, opp["id"], body["id"], decision["id"], "continue_without")
    problem(resp, 404, "not_found")  # not a member: the Opportunity's 404
    assert decision_rows(sync_engine, body["id"])[0]["status"] == "open"
    unknown = resolve(
        client, headers, opp["id"], body["id"], "0190e2c4-0000-7000-8000-000000000000", "replan"
    )
    problem(unknown, 404, "not_found")
    bad = client.post(
        f"{BASE}/{opp['id']}/assessment-runs/{body['id']}/decisions/{decision['id']}/resolve",
        headers={**headers, **if_match(1)},
        json={"choice": "skip"},
    )
    problem(bad, 422, "validation_error")


# --- two open decisions --------------------------------------------------------------------


def test_two_disabled_agents_wait_on_two_decisions_resolved_one_at_a_time(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    set_status(client, admin, "pm_agent", "disabled")
    set_status(client, admin, SECURITY, "disabled")
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    decisions = {d["agent"]: d for d in view(client, headers, opp["id"])["run"]["decisions"]}
    assert {a: d["status"] for a, d in decisions.items()} == {"pm_agent": "open", SECURITY: "open"}
    waiting_rows = [p for p in progress(sync_engine, body["id"]) if p[0].endswith("for_human")]
    assert len(waiting_rows) == 2  # one per open decision

    first = resolve(
        client, headers, opp["id"], body["id"], decisions["pm_agent"]["id"], "continue_without"
    )
    assert first.status_code == 200, first.text
    assert drain(db_url, RESUME) == ["succeeded"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "waiting_for_human"  # it waits on the other decision again
    after = {d["agent"]: d for d in view(client, headers, opp["id"])["run"]["decisions"]}
    assert (after["pm_agent"]["status"], after[SECURITY]["status"]) == ("resolved", "open")
    assert task_rows(sync_engine, body["id"])["pm_agent"]["status"] == "skipped"
    events = trace_rows(sync_engine, opp["id"], "workflows.run.waiting_for_human")
    assert sorted(e["payload"]["decision_id"] for e in events) == sorted(
        d["id"] for d in decisions.values()
    )  # exactly one per decision, none again for the one still open
    again = [p for p in progress(sync_engine, body["id"]) if p[0].endswith("for_human")]
    assert again[2:] == [("workflows.run.waiting_for_human", "security_agent waiting_for_human")]

    second = resolve(
        client,
        headers,
        opp["id"],
        body["id"],
        after[SECURITY]["id"],
        "continue_without",
        after[SECURITY]["row_version"],
    )
    assert second.status_code == 200, second.text
    assert drain(db_url, RESUME) == ["succeeded"]
    (done,) = run_rows(sync_engine, opp["id"])
    assert done["status"] == "succeeded"  # both skips were chosen
    assert done["finished_at"] is not None
    assert fake.calls("engineering_agent") == 1
    assert (fake.calls("pm_agent"), fake.calls(SECURITY)) == (0, 0)


# --- a decision of another run --------------------------------------------------------------


def test_a_decision_of_another_opportunitys_run_is_404(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    admin, _ = _admin(client)
    headers_a, opp_a = prepared(client, sync_engine, db_url, gateway)
    headers_b, opp_b = prepared(client, sync_engine, db_url, gateway)
    set_status(client, admin, SECURITY, "disabled")
    install(AgentGateway(replies()))
    run_a = started(client, headers_a, opp_a["id"])
    run_b = started(client, headers_b, opp_b["id"])
    assert drain(db_url, ASSESS) == ["succeeded", "succeeded"]
    (decision_b,) = view(client, headers_b, opp_b["id"])["run"]["decisions"]

    # B's decision through A's Opportunity and run: not A's.
    wrong = resolve(client, headers_a, opp_a["id"], run_a["id"], decision_b["id"], "replan")
    problem(wrong, 404, "not_found")
    # B's run under A's Opportunity: not A's either.
    wrong_run = resolve(
        client, headers_a, opp_a["id"], run_b["id"], decision_b["id"], "continue_without"
    )
    problem(wrong_run, 404, "not_found")
    (row,) = decision_rows(sync_engine, run_b["id"])
    assert (row["status"], row["row_version"]) == ("open", 1)
    assert run_rows(sync_engine, opp_b["id"])[0]["status"] == "waiting_for_human"


# --- a cancelled decision, then a retry --------------------------------------------------------


def test_a_task_whose_decision_was_closed_runs_when_retried_once_the_agent_is_active(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every attempt dies before the run is marked waiting: the final attempt fails the
    queued task and finishing the run closes its decision. Once the Agent is active again,
    retrying the task runs it."""
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    set_status(client, admin, SECURITY, "disabled")
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])

    async def dies(ctx: Any, run_id: UUID, opportunity_id: UUID) -> bool:
        raise RuntimeError("the worker died")

    with monkeypatch.context() as patched:
        patched.setattr(workflows_runs, "_wait", dies)
        assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    tasks = task_rows(sync_engine, body["id"])
    assert tasks[SECURITY]["status"] == "failed"
    assert run_rows(sync_engine, opp["id"])[0]["status"] == "partially_failed"
    assert decision_rows(sync_engine, body["id"])[0]["status"] == "cancelled"

    set_status(client, admin, SECURITY, "active")
    assert retry(client, headers, opp["id"], body["id"], SECURITY).status_code == 201
    assert drain(db_url, ASSESS) == ["succeeded"]

    assert task_rows(sync_engine, body["id"])[SECURITY]["status"] == "succeeded"
    assert fake.calls(SECURITY) == 1
    assert run_rows(sync_engine, opp["id"])[0]["status"] == "succeeded"
    assert decision_rows(sync_engine, body["id"])[0]["status"] == "cancelled"  # untouched


# --- the grants -----------------------------------------------------------------------------


def test_psa_app_cannot_rewrite_decisions_or_plan_versions(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    _, _, _, body, _ = waiting(client, sync_engine, db_url, gateway)
    for sql in (
        "UPDATE workflows_decisions SET kind = 'plan_escalation' WHERE run_id = :r",
        "UPDATE workflows_decisions SET payload = '{}' WHERE run_id = :r",
        "DELETE FROM workflows_decisions WHERE run_id = :r",
        "UPDATE workflows_plan_versions SET version = 9 WHERE run_id = :r",
        "DELETE FROM workflows_plan_versions WHERE run_id = :r",
    ):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(sql), {"r": body["id"]})


# --- the migration --------------------------------------------------------------------------


def test_a_downgrade_fails_waiting_runs_and_an_upgrade_backfills_plan_v1(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    restore_agents: None,
) -> None:
    _, _, opp, body, _ = waiting(client, sync_engine, db_url, gateway)

    _alembic("downgrade", "0039_tool_gateway")
    try:
        (run,) = run_rows(sync_engine, opp["id"])
        assert run["status"] == "failed"
        tasks = task_rows(sync_engine, body["id"])
        assert (tasks[SECURITY]["status"], tasks[SECURITY]["error_code"]) == (
            "failed",
            "model_timeout",
        )
        assert tasks["pm_agent"]["status"] == "succeeded"
    finally:
        _alembic("upgrade", "head")

    (plan,) = plan_rows(sync_engine, body["id"])
    pinned = task_rows(sync_engine, body["id"])  # as the tasks are now
    assert plan["version"] == 1
    assert (plan["created_by_type"], plan["created_by"]) == ("user", str(opp["owner"]["id"]))
    assert {t["agent"]: t["config_version_id"] for t in plan["tasks"]} == {
        a: str(pinned[a]["config_version_id"]) for a in AGENTS
    }
    assert decision_rows(sync_engine, body["id"]) == []
