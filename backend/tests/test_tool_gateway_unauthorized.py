"""Unauthorized tool calls and the denial audit (Story 7.4) against a real, migrated Postgres
as psa_app: a fake Agent asking for send/write tools, a prompt-injection passage obeyed
literally (the gateway, not the model, is the boundary), the run's pinned config version
against a newer current one, the denial alert threshold and its Resend email job, and the
Admin → Agents → Denied tool calls API (filters, paging, 403, privacy) and its index
migration.

Agents never call tools from model output: executors call the gateway. The injection test
therefore drives a fake Agent that does whatever its input text says.
"""

import asyncio
import json
import os
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.registry.domain.registry import seed_config_version_id
from app.platform.alerts import jobs as alert_jobs
from app.platform.alerts.email import RESEND_URL
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import enqueue
from app.platform.jobs.queue import ClaimedJob
from app.platform.jobs.runner import run_job
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolGateway, ToolOutcome
from app.platform.tool_gateway.catalogue import GAP_LIST, REQUIREMENT_LIST
from app.platform.uow import UnitOfWork, unit_of_work
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_assessments_specialists import (
    AGENTS,
    AgentGateway,
    install,
    prepared,
    replies,
    started,
    tool_call_rows,
)
from tests.test_gaps_detection import rows
from tests.test_intake_extraction import ASSESS, LEASE, drain
from tests.test_intake_parse_job import _alembic
from tests.test_role_admin import _admin, _signed_in
from tests.test_tool_gateway import call_rows, context, denied_events

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run

INJECTION = Path(__file__).parent / "fixtures" / "injection" / "tool_call_passage.txt"
DENIALS = "/api/v1/registry/tool-denials"
AGENTS_URL = "/api/v1/registry/agents"
THRESHOLD_EVENT = "platform.tool_call.denial_threshold_exceeded"
ALERT_JOB = "platform.alert_email"
_TOOL_RE = re.compile(r"\bcall ([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2})")


# --- a fake Agent that obeys its input --------------------------------------------------------


class ObedientAgent:
    """Calls every tool its input text tells it to (`call <tool>`), once each, through the
    ToolGateway: what a fully prompt-injected Agent would do if Agents could call tools."""

    def __init__(self, tools: ToolGateway, ctx: ToolContext) -> None:
        self.tools = tools
        self.ctx = ctx

    @staticmethod
    def requested(text: str) -> list[str]:
        return _TOOL_RE.findall(text)

    async def run(self, uow: UnitOfWork, text: str) -> list[ToolOutcome]:
        return [
            await self.tools.call(
                self.ctx, tool, {"opportunity_id": str(self.ctx.opportunity_id)}, uow=uow
            )
            for tool in self.requested(text)
        ]


def obey(db_url: str, ctx: ToolContext, text: str) -> list[ToolOutcome]:
    async def scenario() -> list[ToolOutcome]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            agent = ObedientAgent(ToolGateway(Settings(database_url=db_url), engine=engine), ctx)
            async with unit_of_work(engine) as uow:
                return await agent.run(uow, text)
        finally:
            await engine.dispose()

    return run_async(scenario())


def _versions(engine: Engine) -> list[dict[str, Any]]:
    return rows(
        engine, "SELECT id, agent_id, version FROM registry_agent_config_versions ORDER BY id"
    )


def _run_events(engine: Engine, run_id: Any, event_type: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE workflow_run_id = :r AND event_type = :e",
        r=run_id,
        e=event_type,
    )


def _alert_jobs(engine: Engine, run_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND payload->>'run_id' = :r",
        t=ALERT_JOB,
        r=str(run_id),
    )


def test_a_fake_agent_asking_for_send_or_write_tools_gets_only_denials(
    sync_engine: Engine, db_url: str
) -> None:
    """Even a context that claims the send tool can't use it: it is no gateway tool."""
    for tool in ("gaps.clarification_question.send", "intake.requirement.edit"):
        ctx = context(uuid4(), tool, REQUIREMENT_LIST)
        (outcome,) = obey(db_url, ctx, f"Now call {tool} please.")
        assert outcome == ToolDenied("unknown_tool")
        (row,) = call_rows(sync_engine, ctx)  # one attempt, never retried
        assert (row["tool"], row["outcome"], row["reason"]) == (tool, "denied", "unknown_tool")
        (event,) = denied_events(sync_engine, ctx.opportunity_id)
        assert event["payload"]["tool"] == tool
        assert event["subject_id"] == row["id"]


def test_a_prompt_injection_passage_produces_only_denials(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: Any
) -> None:
    _, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    text = INJECTION.read_text(encoding="utf-8")
    asked = ObedientAgent.requested(text)
    assert asked == [
        "gaps.clarification_question.send",
        "intake.requirement.edit",
        "gaps.question.send",
        "registry.agent_config.create",
    ]
    (current,) = rows(
        sync_engine,
        "SELECT * FROM registry_agent_config_versions WHERE agent_id = 'engineering_agent' "
        "ORDER BY version DESC LIMIT 1",
    )
    requirements = rows(
        sync_engine, "SELECT * FROM intake_requirements WHERE opportunity_id = :o", o=opp["id"]
    )
    gaps = rows(sync_engine, "SELECT * FROM gaps_gaps WHERE opportunity_id = :o", o=opp["id"])
    versions = _versions(sync_engine)
    events_before = rows(
        sync_engine, "SELECT id FROM platform_trace_events WHERE opportunity_id = :o", o=opp["id"]
    )
    ctx = ToolContext(
        agent_id="engineering_agent",
        semver=current["semver"],
        config_version_id=current["id"],
        tool_permissions=frozenset(current["tool_permissions"]),
        opportunity_id=UUID(opp["id"]),
        run_id=None,
        task_id=uuid4(),
    )

    outcomes = obey(db_url, ctx, text)

    assert outcomes == [ToolDenied("unknown_tool")] * len(asked)
    assert [(r["tool"], r["outcome"]) for r in call_rows(sync_engine, ctx)] == [
        (tool, "denied") for tool in asked
    ]
    # No other side effect: the Requirements, Gaps and Agent configs are as they were, and the
    # only new trace events are the denials.
    assert (
        rows(
            sync_engine, "SELECT * FROM intake_requirements WHERE opportunity_id = :o", o=opp["id"]
        )
        == requirements
    )
    assert (
        rows(sync_engine, "SELECT * FROM gaps_gaps WHERE opportunity_id = :o", o=opp["id"]) == gaps
    )
    assert _versions(sync_engine) == versions
    before = {e["id"] for e in events_before}
    new = [
        e
        for e in rows(
            sync_engine,
            "SELECT * FROM platform_trace_events WHERE opportunity_id = :o",
            o=opp["id"],
        )
        if e["id"] not in before
    ]
    assert sorted(e["event_type"] for e in new) == ["platform.tool_call.denied"] * len(asked)
    # The trace and the audit rows hold no passage text.
    recorded = json.dumps([e["payload"] for e in new]) + str(call_rows(sync_engine, ctx))
    assert "maintenance mode" not in recorded and "out of scope" not in recorded


# --- the pinned config version ----------------------------------------------------------------


@pytest.fixture
def owner_engine() -> Iterator[Engine]:
    owner_url = os.environ.get("PSA_MIGRATIONS_DATABASE_URL")
    if not owner_url:
        pytest.skip("PSA_MIGRATIONS_DATABASE_URL not set (re-pinning a task needs the owner)")
    engine = sa.create_engine(owner_url)
    yield engine
    engine.dispose()


def test_a_newer_current_version_does_not_widen_a_running_tasks_permissions(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    owner_engine: Engine,
) -> None:
    """A run pinned to version 1 (no grants); an administrator then saves a version that
    grants the reads. The run's calls are still denied `tool_not_permitted`."""
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    with owner_engine.begin() as conn:
        for agent in AGENTS:
            conn.execute(
                sa.text(
                    "UPDATE workflows_tasks SET config_version_id = :v "
                    "WHERE run_id = :r AND agent = :a"
                ),
                {"v": seed_config_version_id(agent), "r": body["id"], "a": agent},
            )
    agent = client.get(f"{AGENTS_URL}/engineering_agent", headers=admin).json()
    config = agent["current_config"]
    granted = sorted(
        {*config["tool_permissions"], REQUIREMENT_LIST, GAP_LIST, "knowledge.chunk.read"}
    )
    created = client.post(
        f"{AGENTS_URL}/engineering_agent/config-versions",
        headers={**admin, "If-Match": f'"{agent["row_version"]}"'},
        json={
            **{
                key: config[key]
                for key in (
                    "semver",
                    "model_profile",
                    "prompt_version",
                    "input_schema_version",
                    "output_schema_version",
                    "budgets",
                )
            },
            "tool_permissions": granted,
            "reason": "Pinned-vs-current test",
        },
    )
    assert created.status_code == 201, created.text
    newer = created.json()["current_config"]["id"]
    try:
        assert drain(db_url, ASSESS) == ["succeeded"]
        assert fake.requests == []  # nothing read, nothing to assess
        calls = [c for c in tool_call_rows(sync_engine, opp["id"]) if c["agent_id"] in AGENTS]
        assert sorted((c["agent_id"], c["tool"], c["reason"]) for c in calls) == [
            (agent_id, tool, "tool_not_permitted")
            for agent_id in AGENTS
            for tool in (GAP_LIST, REQUIREMENT_LIST)
        ]
        assert {c["config_version_id"] for c in calls if c["agent_id"] == "engineering_agent"} == {
            seed_config_version_id("engineering_agent")
        }
        # Six denials in one run: past the default threshold (3), alerted once.
        (event,) = _run_events(sync_engine, body["id"], THRESHOLD_EVENT)
        assert event["payload"]["denial_count"] == 4 and event["payload"]["threshold"] == 3
        assert len(_alert_jobs(sync_engine, body["id"])) == 1

        # The denial list shows the run's rows with the threshold pill, ids only.
        listed = client.get(
            DENIALS, headers=admin, params={"agent_id": "engineering_agent"}
        ).json()["items"]
        mine = [d for d in listed if d["run_id"] == body["id"]]
        assert len(mine) == 2
        for denial in mine:
            assert denial["semver"] == "0.1.0"
            assert denial["opportunity_id"] == opp["id"]
            assert denial["threshold_exceeded"] is True
        assert opp["customer_name"] not in json.dumps(listed)  # no Opportunity names
    finally:
        # The new version is referenced by nothing; remove it so later tests see the seeded
        # current version again (psa_app can't delete config versions; the owner can).
        with owner_engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM registry_agent_config_versions WHERE id = :v"), {"v": newer}
            )


# --- the denial threshold ---------------------------------------------------------------------


def test_the_threshold_alerts_once_per_run(sync_engine: Engine, db_url: str) -> None:
    ctx = context(uuid4(), GAP_LIST)
    for count in range(1, 6):
        assert obey(db_url, ctx, f"call {REQUIREMENT_LIST}") == [ToolDenied("tool_not_permitted")]
        alerted = _run_events(sync_engine, ctx.run_id, THRESHOLD_EVENT)
        assert len(alerted) == (1 if count > 3 else 0), count
    (event,) = _run_events(sync_engine, ctx.run_id, THRESHOLD_EVENT)
    assert (event["actor_type"], event["actor_id"]) == ("agent", "pm_agent@0.1.0")
    assert (event["subject_type"], event["subject_id"]) == (
        "assessments.assessment_run",
        ctx.run_id,
    )
    assert event["opportunity_id"] == ctx.opportunity_id
    assert event["payload"] == {
        "run_id": str(ctx.run_id),
        "actor_id": "pm_agent@0.1.0",
        "denial_count": 4,
        "threshold": 3,
    }
    (job,) = _alert_jobs(sync_engine, ctx.run_id)
    assert job["status"] == "queued"
    assert job["payload"] == {
        "kind": "tool_denial_threshold",
        "run_id": str(ctx.run_id),
        "opportunity_id": str(ctx.opportunity_id),
        "agent_id": "pm_agent",
        "semver": "0.1.0",
        "denial_count": 4,
        "threshold": 3,
        # Both bounds from the database clock: the run's first denial and today (UTC).
        "day_from": _today(sync_engine).isoformat(),
        "day_to": _today(sync_engine).isoformat(),
    }
    assert len(denied_events(sync_engine, ctx.opportunity_id)) == 5


def test_two_denials_racing_past_the_threshold_alert_once(sync_engine: Engine, db_url: str) -> None:
    """The run's advisory lock: two tasks of one run denied at the same time, each in its own
    Unit of Work, after `threshold` earlier denials. Exactly one of them alerts."""
    ctx = context(uuid4(), GAP_LIST)
    for _ in range(3):  # the default threshold
        obey(db_url, ctx, f"call {REQUIREMENT_LIST}")
    assert _run_events(sync_engine, ctx.run_id, THRESHOLD_EVENT) == []

    async def scenario() -> list[ToolOutcome]:
        engine = create_engine(Settings(database_url=db_url))
        tools = ToolGateway(Settings(database_url=db_url), engine=engine)

        async def deny() -> ToolOutcome:
            async with unit_of_work(engine) as uow:
                return await tools.call(ctx, REQUIREMENT_LIST, uow=uow)

        try:
            return list(await asyncio.gather(deny(), deny()))
        finally:
            await engine.dispose()

    assert run_async(scenario()) == [ToolDenied("tool_not_permitted")] * 2
    assert len(call_rows(sync_engine, ctx)) == 5
    (event,) = _run_events(sync_engine, ctx.run_id, THRESHOLD_EVENT)
    assert event["payload"]["denial_count"] == 4
    assert len(_alert_jobs(sync_engine, ctx.run_id)) == 1


def test_calls_outside_a_run_never_alert(sync_engine: Engine, db_url: str) -> None:
    base = context(uuid4(), GAP_LIST)
    ctx = ToolContext(
        agent_id=base.agent_id,
        semver=base.semver,
        config_version_id=base.config_version_id,
        tool_permissions=base.tool_permissions,
        opportunity_id=base.opportunity_id,
        run_id=None,
        task_id=base.task_id,
    )
    obey(db_url, ctx, " ".join([f"call {REQUIREMENT_LIST}"] * 5))
    assert len(call_rows(sync_engine, ctx)) == 5
    assert (
        rows(
            sync_engine,
            "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :e",
            o=ctx.opportunity_id,
            e=THRESHOLD_EVENT,
        )
        == []
    )


# --- the alert email job ----------------------------------------------------------------------


def _payload(**overrides: Any) -> alert_jobs.ToolDenialAlert:
    values: dict[str, Any] = {
        "run_id": uuid4(),
        "opportunity_id": uuid4(),
        "agent_id": "pm_agent",
        "semver": "0.1.0",
        "denial_count": 4,
        "threshold": 3,
        "day_from": date(2026, 10, 23),
        "day_to": date(2026, 10, 24),
    }
    return alert_jobs.ToolDenialAlert(**{**values, **overrides})


def _configured(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "resend_api_key": "re_test_key",
        "alert_email_from": "PSA Alerts <alerts@example.test>",
        "alert_email_to": ["ops@example.test", "lead@example.test"],
        "web_base_url": "https://psa.example.test/",
    }
    return Settings(**{**values, **overrides})


class Recorder:
    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, json={"id": "email_1"})


@pytest.fixture
def resend(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    recorder = Recorder()
    monkeypatch.setattr(alert_jobs, "_transport", httpx.MockTransport(recorder))
    monkeypatch.setattr(alert_jobs, "get_settings", _configured)
    yield recorder


def _handle(payload: alert_jobs.ToolDenialAlert) -> None:
    ctx: Any = None  # the handler doesn't read its context
    run_async(alert_jobs.alert_email(ctx, alert_jobs.AlertEmailJob(alert=payload)))


def test_the_alert_job_sends_one_resend_email_with_ids_only(resend: Recorder) -> None:
    payload = _payload()
    _handle(payload)
    (request,) = resend.requests
    assert (request.method, str(request.url)) == ("POST", RESEND_URL)
    assert request.headers["Authorization"] == "Bearer re_test_key"
    body = json.loads(request.content)
    assert set(body) == {"from", "to", "subject", "text"}
    assert body["from"] == "PSA Alerts <alerts@example.test>"
    assert body["to"] == ["ops@example.test", "lead@example.test"]
    # The count is run-wide (every Agent): the subject names no single Agent.
    assert body["subject"] == "[PSA] A run passed 3 denied tool calls"
    text = body["text"]
    for value in (str(payload.run_id), str(payload.opportunity_id), "4", "3"):
        assert value in text
    assert "Last denied call: pm_agent@0.1.0\n" in text
    # The link covers the run's days for every Agent.
    assert "https://psa.example.test/admin/agents/denials?from=2026-10-23&to=2026-10-24\n" in text
    assert "agent_id" not in text


def test_the_alert_job_skips_sending_when_email_is_not_configured(
    resend: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for missing in ({"resend_api_key": None}, {"alert_email_from": ""}, {"alert_email_to": []}):
        monkeypatch.setattr(alert_jobs, "get_settings", lambda m=missing: _configured(**m))
        _handle(_payload())  # completes without raising
    assert resend.requests == []


def _queued_alert(db_url: str) -> UUID:
    async def scenario() -> UUID:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await enqueue(uow, alert_jobs.AlertEmailJob(alert=_payload()))
        finally:
            await engine.dispose()

    return run_async(scenario())


def _run_alert(db_url: str, job_id: UUID) -> str:
    """Claim this one job (not another test's queued alerts) and run it as the worker does."""

    async def scenario() -> str:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                row = (
                    await uow.session.execute(
                        sa.text(
                            "UPDATE platform_jobs SET status = 'running', lease_owner = 'test', "
                            "lease_expires_at = now() + interval '30 seconds', "
                            "attempts = attempts + 1, updated_at = now() WHERE id = :id "
                            "RETURNING id, job_type, payload, attempts, opportunity_id"
                        ),
                        {"id": job_id},
                    )
                ).one()
            job = ClaimedJob(
                id=row.id,
                job_type=row.job_type,
                payload=row.payload,
                attempts=row.attempts,
                opportunity_id=row.opportunity_id,
                lease_owner="test",
            )
            return str(await run_job(engine, job, LEASE))
        finally:
            await engine.dispose()

    return run_async(scenario())


@pytest.mark.parametrize(
    ("recorder", "outcome"),
    [
        (Recorder(200), "succeeded"),
        (Recorder(503), "failed_retrying"),
        (Recorder(429), "failed_retrying"),
        (Recorder(408), "failed_retrying"),
        (Recorder(error=httpx.ConnectError("down")), "failed_retrying"),
        (Recorder(422), "dead"),
        (Recorder(401), "dead"),
    ],
)
def test_resend_5xx_and_network_errors_retry_and_4xx_fails_permanently(
    sync_engine: Engine,
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    recorder: Recorder,
    outcome: str,
) -> None:
    monkeypatch.setattr(alert_jobs, "_transport", httpx.MockTransport(recorder))
    monkeypatch.setattr(alert_jobs, "get_settings", _configured)
    job_id = _queued_alert(db_url)
    assert _run_alert(db_url, job_id) == outcome
    (job,) = rows(sync_engine, "SELECT * FROM platform_jobs WHERE id = :j", j=job_id)
    assert (job["status"], job["attempts"]) == (outcome, 1)
    assert len(recorder.requests) == 1
    if outcome != "succeeded":
        assert "re_test_key" not in (job["last_error"] or "")


# --- the denial list API ----------------------------------------------------------------------


def _deny(db_url: str, agent: str, *, config_version_id: UUID | None = None) -> ToolContext:
    base = context(uuid4(), GAP_LIST, agent=agent)
    ctx = ToolContext(
        agent_id=agent,
        semver="0.1.0",
        config_version_id=config_version_id or base.config_version_id,
        tool_permissions=base.tool_permissions,
        opportunity_id=base.opportunity_id,
        run_id=base.run_id,
        task_id=base.task_id,
    )
    assert obey(db_url, ctx, f"call {REQUIREMENT_LIST}") == [ToolDenied("tool_not_permitted")]
    return ctx


def _today(engine: Engine) -> date:
    (row,) = rows(engine, "SELECT (now() AT TIME ZONE 'UTC')::date AS today")
    today: date = row["today"]
    return today


def _list(client: TestClient, headers: Mapping[str, str], **params: Any) -> dict[str, Any]:
    resp = client.get(DENIALS, headers=dict(headers), params=params)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def test_the_denial_list_filters_by_agent_and_date_newest_first(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    admin, _ = _admin(client)
    first, second = f"t{uuid4().hex[:10]}_agent", f"t{uuid4().hex[:10]}_agent"
    a1 = _deny(db_url, first, config_version_id=seed_config_version_id("pm_agent"))
    b1 = _deny(db_url, second)
    a2 = _deny(db_url, first)

    page = _list(client, admin, agent_id=first)
    assert page["total"] == 2 and (page["page"], page["page_size"]) == (1, 50)
    assert [d["run_id"] for d in page["items"]] == [str(a2.run_id), str(a1.run_id)]
    newest, oldest = page["items"]
    assert set(newest) == {
        "id",
        "created_at",
        "agent_id",
        "semver",
        "config_version_id",
        "tool",
        "reason",
        "opportunity_id",
        "run_id",
        "task_id",
        "threshold_exceeded",
    }
    assert (oldest["agent_id"], oldest["semver"], oldest["tool"], oldest["reason"]) == (
        first,
        "0.1.0",  # the version it called with: the seeded pm_agent v1
        REQUIREMENT_LIST,
        "tool_not_permitted",
    )
    assert oldest["opportunity_id"] == str(a1.opportunity_id)
    assert oldest["task_id"] == str(a1.task_id)
    assert newest["semver"] is None  # a version the registry doesn't hold
    assert newest["threshold_exceeded"] is False
    (only,) = _list(client, admin, agent_id=second)["items"]
    assert only["run_id"] == str(b1.run_id)

    today = _today(sync_engine)
    day = today.isoformat()
    assert _list(client, admin, agent_id=first, **{"from": day, "to": day})["total"] == 2
    tomorrow = (today + timedelta(days=1)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    assert _list(client, admin, agent_id=first, **{"from": tomorrow})["total"] == 0
    assert _list(client, admin, agent_id=first, to=yesterday)["total"] == 0
    assert _list(client, admin, agent_id=first, **{"from": yesterday, "to": tomorrow})["total"] == 2

    # Paging, like Admin → Users.
    second_page = _list(client, admin, agent_id=first, page=2, page_size=1)
    assert second_page["total"] == 2
    assert [d["run_id"] for d in second_page["items"]] == [str(a1.run_id)]
    assert _list(client, admin, agent_id=first, page=3, page_size=1)["items"] == []
    # Every item is a denial, newest first, across Agents.
    everything = _list(client, admin, page_size=200)["items"]
    assert all(d["reason"] for d in everything)
    stamps = [datetime.fromisoformat(d["created_at"]) for d in everything]
    assert stamps == sorted(stamps, reverse=True)
    assert all(
        s.tzinfo is not None and s <= datetime.now(UTC) + timedelta(minutes=1) for s in stamps
    )


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-13-01"},
        {"to": "yesterday"},
        {"from": "2026-10-24T00:00"},
        {"from": "2026-10-25", "to": "2026-10-24"},
        {"page": 0},
        {"page_size": 201},
    ],
)
def test_a_bad_denial_list_query_is_422(client: TestClient, params: dict[str, Any]) -> None:
    admin, _ = _admin(client)
    resp = client.get(DENIALS, headers=admin, params=params)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "validation_error"


def test_only_platform_administrators_read_the_denial_list(client: TestClient) -> None:
    for role in ("presales_engineer", "head_of_delivery", "sales_representative"):
        headers, _ = _signed_in(client, f"User {role}", role)
        resp = client.get(DENIALS, headers=headers)
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "forbidden"
    assert client.get(DENIALS).status_code == 401


# --- the migration ----------------------------------------------------------------------------


def test_the_agent_index_migration_downgrades_and_upgrades(sync_engine: Engine) -> None:
    def indexes() -> set[str]:
        return {
            r["indexname"]
            for r in rows(
                sync_engine,
                "SELECT indexname FROM pg_indexes WHERE tablename = 'platform_tool_calls'",
            )
        }

    def versions() -> list[dict[str, Any]]:
        return rows(sync_engine, "SELECT * FROM registry_agent_config_versions ORDER BY id")

    before = versions()
    added = {
        "ix_platform_tool_calls_denied_agent_id_created_at",
        "ix_platform_tool_calls_denied_created_at_id",
    }
    assert added <= indexes()
    _alembic("downgrade", "0045_registry_config_reason")
    try:
        assert not added & indexes()
    finally:
        _alembic("upgrade", "head")
    assert added <= indexes()
    (partial,) = rows(
        sync_engine,
        "SELECT indexdef FROM pg_indexes WHERE indexname = :n",
        n="ix_platform_tool_calls_denied_created_at_id",
    )
    assert "WHERE (outcome = 'denied'::text)" in partial["indexdef"]
    assert versions() == before  # config versions are never rewritten


def test_a_legacy_flat_denial_alert_payload_still_loads_and_dumps_flat() -> None:
    """Story 10.6: rows queued before the alert union hold a flat `ToolDenialAlert` (no
    `alert` key); they load into `AlertEmailJob` and dump back to the same flat form."""
    legacy = _payload().model_dump(mode="json")
    assert "alert" not in legacy and legacy["kind"] == "tool_denial_threshold"
    job = alert_jobs.AlertEmailJob.model_validate(legacy)
    assert isinstance(job.alert, alert_jobs.ToolDenialAlert)
    assert job.alert.run_id == UUID(legacy["run_id"])
    assert job.model_dump(mode="json") == legacy
