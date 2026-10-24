"""The ToolGateway (Story 5.4): the catalogue holds READ tools only, each an `identity`
action; every call is permission-checked, scoped to the task's Opportunity and recorded in
`platform_tool_calls`; denials are typed values and traced as `platform.tool_call.denied`,
with ids and codes only. DB-backed tests run against a migrated Postgres as psa_app."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

import app.modules.gaps.application.public
import app.modules.intake.application.public
import app.modules.knowledge.application.public  # noqa: F401 - registers the handlers
from app.modules.identity.actions import (
    ACTION_CATEGORIES,
    Action,
    PermissionCategory,
    action_category,
)
from app.modules.intake.application.requirement_refs import RequirementSnapshot
from app.modules.registry.domain.registry import SEED_NAMESPACE
from app.platform import tool_gateway
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.tool_gateway import (
    READ_TOOLS,
    TOOLS,
    ToolContext,
    ToolDenied,
    ToolGateway,
    ToolOutcome,
    ToolResult,
)
from app.platform.tool_gateway.catalogue import (
    CATALOGUE_ENTRY_LIST,
    CHUNK_READ,
    GAP_LIST,
    PASSAGE_READ,
    REQUIREMENT_LIST,
    RESEARCH_PAGE_FETCH,
)
from app.platform.uow import unit_of_work
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_estimates_draft import detected
from tests.test_gaps_detection import rows
from tests.test_intake_extraction import FakeGateway

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile

STORY_5_4_TOOLS = frozenset(
    {
        "intake.requirement.list",
        "intake.passage.read",
        "knowledge.chunk.search",
        "knowledge.chunk.read",
        "knowledge.catalogue_entry.list",
        "gaps.gap.list",
        "knowledge.research_page.fetch",
    }
)
SPECIALISTS = ("engineering_agent", "pm_agent", "security_agent")
SEEDED = (
    "clarification_agent",
    "conflict_agent",
    "estimating_agent",
    "intake_agent",
    "opportunity_intake_agent",
    "red_team_agent",
    *SPECIALISTS,
)


def context(opportunity_id: UUID | str, *tools: str, agent: str = "pm_agent") -> ToolContext:
    return ToolContext(
        agent_id=agent,
        semver="0.1.0",
        config_version_id=uuid4(),
        tool_permissions=frozenset(tools),
        opportunity_id=UUID(str(opportunity_id)),
        run_id=uuid4(),
        task_id=uuid4(),
    )


def call(
    db_url: str, ctx: ToolContext, tool: str, args: Mapping[str, Any] | None = None
) -> ToolOutcome:
    async def scenario() -> ToolOutcome:
        engine = create_engine(Settings(database_url=db_url))
        try:
            gateway = ToolGateway(Settings(database_url=db_url), engine=engine)
            async with unit_of_work(engine) as uow:  # a caller's Unit of Work (the node's)
                inside = await gateway.call(ctx, tool, args, uow=uow)
            return inside
        finally:
            await engine.dispose()

    return run_async(scenario())


def call_rows(engine: Engine, ctx: ToolContext) -> list[dict[str, Any]]:
    return rows(
        engine, "SELECT * FROM platform_tool_calls WHERE task_id = :t ORDER BY id", t=ctx.task_id
    )


def denied_events(engine: Engine, opportunity_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = 'platform.tool_call.denied' ORDER BY occurred_at, id",
        o=opportunity_id,
    )


# --- the catalogue --------------------------------------------------------------------------


def test_the_catalogue_is_read_only_and_every_tool_is_an_action() -> None:
    assert READ_TOOLS >= STORY_5_4_TOOLS
    actions = {a.value for a in Action}
    for name in TOOLS:
        assert name in actions
        verb = name.rsplit(".", 1)[1]
        assert verb in {"list", "read", "search", "fetch"}, name
        for forbidden in ("write", "edit", "delete", "send", "approve", "create", "update"):
            assert forbidden not in name
    assert TOOLS[RESEARCH_PAGE_FETCH].network
    assert not any(spec.network for name, spec in TOOLS.items() if name != RESEARCH_PAGE_FETCH)


def test_every_action_has_one_category_and_every_tool_is_a_read() -> None:
    """Story 7.4: one category per action; the ToolGateway holds `read` actions only."""
    missing = [a for a in Action if a not in ACTION_CATEGORIES]
    assert missing == [], f"actions without a permission category: {missing}"
    assert set(ACTION_CATEGORIES) == set(Action)
    assert {c.value for c in PermissionCategory} == {"read", "write", "delete", "send", "approve"}
    for name in TOOLS:
        assert action_category(name) == PermissionCategory.READ, name
    assert action_category("intake.requirement.edit") == PermissionCategory.WRITE
    assert action_category("gaps.clarification_question.send") == PermissionCategory.SEND
    assert action_category("gaps.question.send") is None


def test_every_tool_has_a_handler_once_the_owning_modules_are_imported() -> None:
    assert tool_gateway.registered_tools() >= STORY_5_4_TOOLS


def test_no_human_role_is_granted_a_tool() -> None:
    from app.modules.identity.domain import policy

    granted = (
        policy.OWNER_GRANTS
        | policy.MEMBER_GRANTS
        | policy.KNOWLEDGE_SOURCE_OWNER_GRANTS
        | policy.ANY_ROLE_GRANTS
    )
    # `knowledge.chunk.search` is also the human Knowledge search (Story 3.3).
    assert {a.value for a in granted} & READ_TOOLS == {"knowledge.chunk.search"}


def test_registering_a_non_catalogue_or_network_tool_is_refused() -> None:
    async def handler(uow: Any, ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
        return ToolResult()

    with pytest.raises(ValueError):
        tool_gateway.register_tool("intake.requirement.edit", handler)
    with pytest.raises(ValueError):
        tool_gateway.register_tool(RESEARCH_PAGE_FETCH, handler)
    with pytest.raises(ValueError):
        tool_gateway.register_tool(REQUIREMENT_LIST, handler)  # already registered


def test_the_research_fetch_refuses_an_open_unit_of_work(db_url: str) -> None:
    ctx = context(uuid4(), RESEARCH_PAGE_FETCH)
    with pytest.raises(RuntimeError, match="Unit of Work"):
        call(db_url, ctx, RESEARCH_PAGE_FETCH, {"url": "https://example.com/"})


# --- the seeded configs ---------------------------------------------------------------------


def test_the_specialists_current_configs_grant_the_two_reads_and_no_one_the_fetch(
    sync_engine: Engine,
) -> None:
    current = {
        r["agent_id"]: r
        for r in rows(
            sync_engine,
            "SELECT v.* FROM registry_agent_config_versions v WHERE v.version = "
            "(SELECT max(version) FROM registry_agent_config_versions w "
            "WHERE w.agent_id = v.agent_id)",
        )
    }
    for agent in SPECIALISTS:
        assert set(current[agent]["tool_permissions"]) >= {REQUIREMENT_LIST, GAP_LIST}
    original = rows(
        sync_engine,
        "SELECT * FROM registry_agent_config_versions WHERE id = ANY(:ids)",
        ids=[uuid5(SEED_NAMESPACE, f"{a}/config/tool-gateway") for a in SPECIALISTS],
    )
    assert len(original) == 3
    for row in original:
        assert row["tool_permissions"] == [REQUIREMENT_LIST, GAP_LIST]
        assert row["version"] >= 2 and row["created_by"] is None
    for agent in SEEDED:
        assert RESEARCH_PAGE_FETCH not in current[agent]["tool_permissions"]


# --- calls ----------------------------------------------------------------------------------


def test_an_allowed_read_returns_the_data_and_leaves_an_ok_row(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=3, queue_draft=False)
    ctx = context(opp["id"], REQUIREMENT_LIST, GAP_LIST)

    outcome = call(db_url, ctx, REQUIREMENT_LIST)
    assert isinstance(outcome, ToolResult)
    assert [type(i) for i in outcome.items] == [RequirementSnapshot] * 3
    assert [i.number for i in outcome.items] == [1, 2, 3]
    gaps = call(db_url, ctx, GAP_LIST)
    assert isinstance(gaps, ToolResult) and gaps.result_count == 1

    recorded = call_rows(sync_engine, ctx)
    assert [
        (r["tool"], r["outcome"], r["reason"], r["result_count"], r["http_status"])
        for r in recorded
    ] == [(REQUIREMENT_LIST, "ok", None, 3, None), (GAP_LIST, "ok", None, 1, None)]
    for row in recorded:
        assert (row["opportunity_id"], row["run_id"], row["agent_id"]) == (
            UUID(opp["id"]),
            ctx.run_id,
            "pm_agent",
        )
        assert row["config_version_id"] == ctx.config_version_id
        assert row["duration_ms"] >= 0
    assert denied_events(sync_engine, opp["id"]) == []


def test_a_tool_the_config_lacks_is_denied_and_traced(sync_engine: Engine, db_url: str) -> None:
    opportunity_id = uuid4()
    ctx = context(opportunity_id, GAP_LIST)
    outcome = call(db_url, ctx, REQUIREMENT_LIST)
    assert outcome == ToolDenied("tool_not_permitted")
    (row,) = call_rows(sync_engine, ctx)
    assert (row["outcome"], row["reason"], row["result_count"]) == (
        "denied",
        "tool_not_permitted",
        0,
    )
    (event,) = denied_events(sync_engine, opportunity_id)
    assert (event["actor_type"], event["actor_id"]) == ("agent", "pm_agent@0.1.0")
    assert (event["subject_type"], event["subject_id"]) == ("platform.tool_call", row["id"])
    assert event["workflow_run_id"] == ctx.run_id
    assert event["payload"] == {
        "actor_id": "pm_agent@0.1.0",
        "tool": REQUIREMENT_LIST,
        "reason": "tool_not_permitted",
        "task_id": str(ctx.task_id),
    }


def test_an_unknown_or_write_tool_is_denied_as_unknown(sync_engine: Engine, db_url: str) -> None:
    ctx = context(uuid4(), "intake.requirement.edit")
    assert call(db_url, ctx, "intake.requirement.edit") == ToolDenied("unknown_tool")
    assert call(db_url, ctx, "no.such.tool") == ToolDenied("unknown_tool")
    assert [(r["tool"], r["reason"]) for r in call_rows(sync_engine, ctx)] == [
        ("intake.requirement.edit", "unknown_tool"),
        ("no.such.tool", "unknown_tool"),
    ]


def test_a_passage_of_another_opportunity_is_out_of_scope_and_returns_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2, queue_draft=False)
    (passage,) = rows(
        sync_engine,
        "SELECT p.id FROM intake_source_passages p JOIN intake_sources s ON s.id = p.source_id "
        "WHERE s.opportunity_id = :o ORDER BY p.start LIMIT 1",
        o=opp["id"],
    )
    own = context(opp["id"], PASSAGE_READ)
    read = call(db_url, own, PASSAGE_READ, {"passage_ids": [str(passage["id"])]})
    assert isinstance(read, ToolResult) and read.result_count == 1
    assert read.items[0].passage_id == passage["id"]

    other_opportunity = uuid4()
    other = context(other_opportunity, PASSAGE_READ)
    assert call(db_url, other, PASSAGE_READ, {"passage_ids": [str(passage["id"])]}) == ToolDenied(
        "out_of_scope"
    )
    # An id argument naming another Opportunity is denied before any handler runs.
    assert call(
        db_url, own, PASSAGE_READ, {"passage_ids": [passage["id"]], "opportunity_id": uuid4()}
    ) == ToolDenied("out_of_scope")
    assert call(db_url, own, PASSAGE_READ, {"passage_ids": ["not-a-uuid"]}) == ToolDenied(
        "out_of_scope"
    )
    (row,) = call_rows(sync_engine, other)
    assert (row["outcome"], row["reason"], row["result_count"]) == ("denied", "out_of_scope", 0)
    (event,) = denied_events(sync_engine, other_opportunity)
    assert event["payload"]["reason"] == "out_of_scope"

    # Privacy: rows and trace hold ids and codes only.
    texts = [
        r["text"]
        for r in rows(
            sync_engine,
            "SELECT text FROM intake_requirements WHERE opportunity_id = :o",
            o=opp["id"],
        )
    ]
    recorded = str(call_rows(sync_engine, own)) + str(denied_events(sync_engine, opp["id"]))
    for text in texts:
        assert text not in recorded


def test_knowledge_reads_unknown_chunks_are_out_of_scope_and_the_catalogue_lists(
    sync_engine: Engine, db_url: str
) -> None:
    ctx = context(uuid4(), CHUNK_READ, CATALOGUE_ENTRY_LIST)
    assert call(db_url, ctx, CHUNK_READ, {"chunk_ids": [str(uuid4())]}) == ToolDenied(
        "out_of_scope"
    )
    listed = call(db_url, ctx, CATALOGUE_ENTRY_LIST, {"kind": "integration_type"})
    assert isinstance(listed, ToolResult)
    assert all(entry.kind == "integration_type" for entry in listed.items)
    assert call(db_url, ctx, CATALOGUE_ENTRY_LIST, {"kind": "nope"}) == ToolDenied("out_of_scope")
    assert call(db_url, ctx, CATALOGUE_ENTRY_LIST, {"kind": 5}) == ToolDenied("out_of_scope")


def test_the_application_role_cannot_change_or_delete_tool_call_rows(sync_engine: Engine) -> None:
    for statement in (
        "UPDATE platform_tool_calls SET outcome = 'ok' WHERE false",
        "DELETE FROM platform_tool_calls WHERE false",
    ):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(statement))
