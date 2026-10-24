"""The DB-owned Agent Registry (Story 7.1) against a real, migrated Postgres as psa_app: the
seed and its backfill, the spec's I/O matrix (register, new version, not deployed, bad
contract, bad or duplicate id, disable), 403/412/428, the grants, trace events, disabled
Agents in assessment runs and single-agent steps, run pinning, the profile override, the
manifest's drift check and that no runtime path reads the agents' old code constants.

Tests that disable a seeded Agent restore it (`restore_agents`): the registry is shared by
every test. New config versions go on test Agents (`t<hex>_agent`) registered against a
patched manifest, except the pinning test, which adds a version of `engineering_agent` equal
to its current one apart from its id.
"""

import ast
import importlib.util
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine

from app.agents import manifest as deployed
from app.modules.opportunities.application import imports
from app.modules.registry.application import public as registry
from app.modules.registry.domain import registry as rules
from app.platform.config import Settings
from app.platform.model_gateway.port import ModelUnavailableError
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_assumptions as assumption_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests import test_opportunity_imports as import_tests
from tests.test_assessments_red_team import drafted as red_team_drafted
from tests.test_assessments_specialists import (
    AGENTS,
    AgentGateway,
    assessment_rows,
    install,
    prepared,
    replies,
    started,
    task_rows,
)
from tests.test_gaps_detection import detections, extracted, rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import (
    ASSESS,
    BASE,
    DETECT,
    DRAFT,
    EXTRACT,
    HIDDEN,
    PROPOSE,
    RED_TEAM,
    RESUME,
    drain,
    parsed,
)
from tests.test_intake_parse_job import _alembic
from tests.test_role_admin import _admin, _signed_in

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run

URL = "/api/v1/registry/agents"
BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "versions" / "20261013_0026_registry.py"
MIGRATION_0033 = BACKEND / "migrations" / "versions" / "20261020_0033_conflict_agent.py"
SEEDED_0026 = (
    ("clarification_agent", "Clarification Agent"),
    ("engineering_agent", "Engineering Agent"),
    ("estimating_agent", "Estimating Agent"),
    ("intake_agent", "Intake Agent"),
    ("opportunity_intake_agent", "Opportunity Intake Agent"),
    ("pm_agent", "PM Agent"),
    ("red_team_agent", "Red Team Agent"),
    ("security_agent", "Security Agent"),
)
SEEDED_0033 = (("conflict_agent", "Conflict Agent"),)
"""Story 6.2 seeds the Conflict Agent the same way."""
SEEDED = SEEDED_0026 + SEEDED_0033
MIGRATION_0039 = BACKEND / "migrations" / "versions" / "20261024_0041_critic_review.py"
SEEDED_0039 = (("critic_agent", "Critic Agent"),)
"""Story 6.4 seeds the Critic Agent the same way, granting the `assessments.run.read` tool."""
EVERY_SEEDED = SEEDED + SEEDED_0039
CODES = {
    403: "forbidden",
    404: "not_found",
    409: "registry_agent_duplicate",
    412: "row_version_mismatch",
    422: "validation_error",
    428: "if_match_required",
}


def _problem(resp: Response, status: int, code: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body: dict[str, Any] = resp.json()
    assert_problem(body, status, code or CODES[status])
    return body


def _if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def _config(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "semver": "0.2.0",
        "model_profile": "local-chat",
        "prompt_version": 1,
        "input_schema_version": 1,
        "output_schema_version": 1,
        "tool_permissions": ["intake.requirement.list"],
        "budgets": {"max_tokens_per_run": 20000},
    }
    return {**body, **overrides}


def _agent_rows(engine: Engine, agent_id: str) -> dict[str, Any]:
    (row,) = rows(engine, "SELECT * FROM registry_agents WHERE agent_id = :a", a=agent_id)
    return row


def _version_rows(engine: Engine, agent_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM registry_agent_config_versions WHERE agent_id = :a ORDER BY version",
        a=agent_id,
    )


def _events(engine: Engine, subject_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE subject_id = :s ORDER BY occurred_at, id",
        s=subject_id,
    )


@pytest.fixture
def test_manifest(monkeypatch: pytest.MonkeyPatch) -> str:
    """A fresh test Agent id, deployed in a patched manifest (prompt 1 and 2, schemas 1, and
    an output schema v2 written for contract version "2")."""
    agent_id = f"t{uuid4().hex[:10]}_agent"
    data = json.loads(json.dumps(dict(deployed.load().data)))
    data["prompts"][agent_id] = {"1": {"v1.md": "0" * 64}, "2": {"v2.md": "1" * 64}}
    data["schemas"][agent_id] = {
        "input": {"1": {"sha256": "2" * 64, "contract_version": "1"}},
        "output": {
            "1": {"sha256": "3" * 64, "contract_version": "1"},
            "2": {"sha256": "4" * 64, "contract_version": "2"},
        },
    }
    monkeypatch.setattr(deployed, "load", lambda: deployed.Manifest(data))
    return agent_id


@pytest.fixture
def restore_agents(sync_engine: Engine) -> Iterator[None]:
    """Put every seeded Agent back to `active` after the test."""
    yield
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE registry_agents SET status = 'active', row_version = row_version + 1 "
                "WHERE agent_id = ANY(:ids) AND status <> 'active'"
            ),
            {"ids": [agent_id for agent_id, _ in EVERY_SEEDED]},
        )


def _register(client: TestClient, headers: dict[str, str], agent_id: str) -> dict[str, Any]:
    resp = client.post(
        URL, headers=headers, json={"agent_id": agent_id, "name": "Test Agent", "config": _config()}
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _set_status(
    client: TestClient, headers: dict[str, str], agent_id: str, status: str
) -> dict[str, Any]:
    current = client.get(f"{URL}/{agent_id}", headers=headers)
    assert current.status_code == 200, current.text
    resp = client.post(
        f"{URL}/{agent_id}/status",
        headers={**headers, **_if_match(current.json()["row_version"])},
        json={"status": status},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


# --- without a database -------------------------------------------------------------------


def test_the_committed_manifest_matches_the_code() -> None:
    committed = deployed.MANIFEST_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == deployed.render(deployed.build())
    assert deployed.main(["--check"]) == 0


def test_the_manifest_lists_every_prompt_schema_and_profile() -> None:
    manifest = deployed.load()
    for agent_id, _ in EVERY_SEEDED:
        assert manifest.has_prompt(agent_id, 1), agent_id
        assert manifest.schema(agent_id, "input", 1) is not None
        output = manifest.schema(agent_id, "output", 1)
        assert output is not None and output["contract_version"] == "1"
        assert not manifest.has_prompt(agent_id, 2)
    # Prompt version N covers `v<N>.md` and `v<N>-*.md`.
    assert set(manifest.data["prompts"]["estimating_agent"]["1"]) == {
        "v1.md",
        "v1-assumptions.md",
    }
    assert manifest.has_profile("demo-chat") and not manifest.has_profile("gpt-9")


def test_prompt_hashes_ignore_line_endings(tmp_path: Path) -> None:
    lf, crlf = tmp_path / "lf.md", tmp_path / "crlf.md"
    lf.write_bytes(b"one\ntwo\n")
    crlf.write_bytes(b"one\r\ntwo\r\n")
    assert deployed.prompt_hash(lf) == deployed.prompt_hash(crlf)


@pytest.mark.parametrize(
    ("path", "seeded", "agent_id"),
    [
        (MIGRATION, SEEDED_0026, "pm_agent"),
        (MIGRATION_0033, SEEDED_0033, "conflict_agent"),
        (MIGRATION_0039, SEEDED_0039, "critic_agent"),
    ],
)
def test_the_migration_seed_matches_the_domain_and_never_imports_the_app(
    path: Path, seeded: tuple[tuple[str, str], ...], agent_id: str
) -> None:
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SEED_NAMESPACE == rules.SEED_NAMESPACE
    assert module.SEED_AGENTS == seeded
    assert module._agent_row_id(agent_id) == rules.agent_row_id(agent_id)
    assert module._seed_version_id(agent_id) == rules.seed_config_version_id(agent_id)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name == "app" or name.startswith("app.") for name in imported)


def test_no_runtime_path_reads_the_agents_code_constants() -> None:
    """The agents' `AGENT_ID` / `SEMVER` / `PROMPT_VERSION` constants and `config(profile)`
    functions are gone; config comes only from the registry."""
    agents_dir = BACKEND / "app" / "agents"
    for path in agents_dir.glob("*/agent.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert not names & {"AGENT_ID", "SEMVER", "PROMPT_VERSION"}, path
        assert "config" not in functions, path
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.agents."):
                imported = {alias.name for alias in node.names}
                assert not imported & {"AGENT_ID", "SEMVER", "PROMPT_VERSION", "config"}, path


def test_agent_id_rules() -> None:
    assert rules.agent_id(" security_agent ") == "security_agent"
    for bad in ("Foo", "engineering", "_agent", "9_agent", "a-b_agent", ""):
        with pytest.raises(ValueError):
            rules.agent_id(bad)
    with pytest.raises(ValueError):
        rules.tool_permissions(["Not An Action"])
    assert rules.tool_permissions(["gaps.gap.list", "gaps.gap.list"]) == ("gaps.gap.list",)
    for write in ("intake.requirement.edit", "a.b.read", "gaps.clarification_question.send"):
        with pytest.raises(rules.ToolPermissionNotReadOnly):
            rules.tool_permissions([write])


def test_the_profile_override_applies_only_when_set_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PSA_MODEL_PROFILE_CHAT", raising=False)
    version = rules.ConfigVersion(
        id=uuid4(),
        agent_id="pm_agent",
        version=1,
        semver="0.1.0",
        model_profile="demo-chat",
        model_digest="unpinned",
        prompt_version=1,
        input_schema_version=1,
        output_schema_version=1,
        contract_version="1",
        tool_permissions=(),
        budgets={},
        created_by=None,
        created_at=None,  # type: ignore[arg-type]
    )
    assert registry.effective_profile(version, Settings()) == "demo-chat"
    monkeypatch.setenv("PSA_MODEL_PROFILE_CHAT", "local-chat")
    config = registry.agent_config(version, Settings())
    assert (config.profile, config.config_version_id, config.actor_id) == (
        "local-chat",
        version.id,
        "pm_agent@0.1.0",
    )


# --- the seed and its backfill --------------------------------------------------------------


def test_the_seeded_agents_are_active_at_version_one(sync_engine: Engine) -> None:
    for agent_id, name in SEEDED:
        agent = _agent_rows(sync_engine, agent_id)
        assert (agent["id"], agent["name"]) == (rules.agent_row_id(agent_id), name)
        first = _version_rows(sync_engine, agent_id)[0]
        assert first["id"] == rules.seed_config_version_id(agent_id)
        assert first["id"] == uuid5(rules.SEED_NAMESPACE, f"{agent_id}/config/1")
        assert (
            first["version"],
            first["semver"],
            first["model_profile"],
            first["model_digest"],
            first["prompt_version"],
            first["input_schema_version"],
            first["output_schema_version"],
            first["contract_version"],
            first["tool_permissions"],
            first["budgets"],
            first["created_by"],
        ) == (1, "0.1.0", "demo-chat", "unpinned", 1, 1, 1, "1", [], {}, None)


def test_the_migration_backfills_existing_assessments_to_version_one(
    sync_engine: Engine,
) -> None:
    run_id, task_id, assessment_id, opportunity_id = uuid4(), uuid4(), uuid4(), uuid4()
    _alembic("downgrade", "0025_knowledge_sources")
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO assessments_runs (id, opportunity_id, status) "
                    "VALUES (:r, :o, 'succeeded')"
                ),
                {"r": run_id, "o": opportunity_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO assessments_tasks (id, run_id, agent, status) "
                    "VALUES (:t, :r, 'security_agent', 'succeeded')"
                ),
                {"t": task_id, "r": run_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO assessments_assessments (id, opportunity_id, agent, version, "
                    "run_id, status, recommendation, confidence, confidence_basis, "
                    "dropped_count) VALUES (:a, :o, 'security_agent', 1, :r, 'current', "
                    "'proceed', 'high', 'basis', 0)"
                ),
                {"a": assessment_id, "o": opportunity_id, "r": run_id},
            )
    finally:
        _alembic("upgrade", "head")
    seeded = rules.seed_config_version_id("security_agent")
    (assessment,) = rows(
        sync_engine, "SELECT * FROM assessments_assessments WHERE id = :a", a=assessment_id
    )
    (task,) = rows(sync_engine, "SELECT * FROM workflows_tasks WHERE id = :t", t=task_id)
    assert assessment["config_version_id"] == seeded
    assert (task["config_version_id"], task["skip_reason"]) == (seeded, None)
    assert [a["status"] for a in rows(sync_engine, "SELECT status FROM registry_agents")] == [
        "active"
    ] * len(EVERY_SEEDED)


# --- the API --------------------------------------------------------------------------------


def test_admins_list_and_read_agents(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client)
    resp = client.get(URL, headers=admin)
    assert resp.status_code == 200, resp.text
    listed = {a["agent_id"]: a for a in resp.json()["items"]}
    assert set(listed) >= {agent_id for agent_id, _ in SEEDED}
    pm = client.get(f"{URL}/pm_agent", headers=admin)
    assert pm.status_code == 200
    assert pm.headers["ETag"] == f'"{pm.json()["row_version"]}"'
    assert pm.json()["current_config"]["agent_id"] == "pm_agent"
    versions = client.get(f"{URL}/pm_agent/config-versions", headers=admin).json()["items"]
    assert versions[-1]["id"] == str(rules.seed_config_version_id("pm_agent"))
    _problem(client.get(f"{URL}/nobody_agent", headers=admin), 404)


def test_non_admins_get_403_on_every_registry_endpoint(client: TestClient) -> None:
    for role in ("presales_engineer", "head_of_delivery", "sales_representative"):
        headers, _ = _signed_in(client, f"User {role}", role)
        _problem(client.get(URL, headers=headers), 403)
        _problem(client.get(f"{URL}/pm_agent", headers=headers), 403)
        _problem(client.get(f"{URL}/pm_agent/config-versions", headers=headers), 403)
        _problem(
            client.post(
                URL,
                headers=headers,
                json={"agent_id": "new_agent", "name": "N", "config": _config()},
            ),
            403,
        )
        _problem(
            client.post(
                f"{URL}/pm_agent/config-versions",
                headers={**headers, **_if_match(1)},
                json=_config(),
            ),
            403,
        )
        _problem(
            client.post(
                f"{URL}/pm_agent/status",
                headers={**headers, **_if_match(1)},
                json={"status": "disabled"},
            ),
            403,
        )


def test_register_inserts_the_agent_and_version_one_with_a_trace_event(
    client: TestClient, sync_engine: Engine, test_manifest: str
) -> None:
    admin, admin_id = _admin(client)
    agent = _register(client, admin, test_manifest)
    assert (agent["agent_id"], agent["status"], agent["row_version"]) == (
        test_manifest,
        "active",
        1,
    )
    assert agent["id"] == str(rules.agent_row_id(test_manifest))
    config = agent["current_config"]
    assert (config["version"], config["semver"], config["model_digest"]) == (1, "0.2.0", "unpinned")
    assert (config["contract_version"], config["created_by_id"]) == ("1", str(admin_id))
    assert config["tool_permissions"] == ["intake.requirement.list"]
    assert config["budgets"] == {"max_tokens_per_run": 20000}
    (event,) = _events(sync_engine, agent["id"])
    assert event["event_type"] == "registry.agent.registered"
    assert (event["opportunity_id"], event["actor_id"]) == (None, str(admin_id))
    assert event["payload"] == {
        "agent_id": test_manifest,
        "status": "active",
        "from_config_version_id": None,
        "to_config_version_id": config["id"],
    }


@pytest.mark.parametrize("agent_id", ["Foo", "engineering", "x" * 70 + "_agent"])
def test_a_bad_agent_id_is_422(client: TestClient, agent_id: str) -> None:
    admin, _ = _admin(client)
    resp = client.post(
        URL, headers=admin, json={"agent_id": agent_id, "name": "N", "config": _config()}
    )
    _problem(resp, 422)


def test_a_duplicate_agent_id_is_409(client: TestClient, sync_engine: Engine) -> None:
    admin, _ = _admin(client)
    before = len(_version_rows(sync_engine, "pm_agent"))
    resp = client.post(
        URL,
        headers=admin,
        json={"agent_id": "pm_agent", "name": "Another PM", "config": _config(semver="0.1.0")},
    )
    _problem(resp, 409)
    assert len(_version_rows(sync_engine, "pm_agent")) == before


def test_a_new_version_becomes_current_with_a_trace_event(
    client: TestClient, sync_engine: Engine, test_manifest: str
) -> None:
    admin, admin_id = _admin(client)
    agent = _register(client, admin, test_manifest)
    v1 = agent["current_config"]["id"]
    url = f"{URL}/{test_manifest}/config-versions"
    _problem(client.post(url, headers=admin, json=_config(prompt_version=2)), 428)
    _problem(client.post(url, headers={**admin, **_if_match(9)}, json=_config()), 412)
    resp = client.post(
        url, headers={**admin, **_if_match(1)}, json=_config(semver="0.3.0", prompt_version=2)
    )
    assert resp.status_code == 201, resp.text
    changed = resp.json()
    assert resp.headers["ETag"] == '"2"'
    assert (changed["current_config"]["version"], changed["current_config"]["prompt_version"]) == (
        2,
        2,
    )
    v2 = changed["current_config"]["id"]
    versions = client.get(url, headers=admin).json()["items"]
    assert [v["id"] for v in versions] == [v2, v1]  # newest first; v1 unchanged
    assert versions[1]["semver"] == "0.2.0"
    event = _events(sync_engine, agent["id"])[-1]
    assert event["event_type"] == "registry.agent_config.version_created"
    assert (event["opportunity_id"], event["actor_id"], event["subject_version"]) == (
        None,
        str(admin_id),
        2,
    )
    assert event["payload"] == {
        "agent_id": test_manifest,
        "version": 2,
        "from_config_version_id": v1,
        "to_config_version_id": v2,
    }
    # Runs resolve the new current version.
    assert _version_rows(sync_engine, test_manifest)[-1]["id"] == UUID(v2)


@pytest.mark.parametrize(
    "overrides",
    [
        {"prompt_version": 3},
        {"input_schema_version": 2},
        {"output_schema_version": 5},
        {"model_profile": "gpt-9"},
    ],
)
def test_a_config_outside_the_manifest_is_422_not_deployed(
    client: TestClient, sync_engine: Engine, test_manifest: str, overrides: dict[str, Any]
) -> None:
    admin, _ = _admin(client)
    _register(client, admin, test_manifest)
    resp = client.post(
        f"{URL}/{test_manifest}/config-versions",
        headers={**admin, **_if_match(1)},
        json=_config(**overrides),
    )
    _problem(resp, 422, "registry_config_not_deployed")
    assert len(_version_rows(sync_engine, test_manifest)) == 1
    assert _agent_rows(sync_engine, test_manifest)["row_version"] == 1
    # Registering is checked the same way.
    other = f"t{uuid4().hex[:10]}_agent"
    resp = client.post(
        URL, headers=admin, json={"agent_id": other, "name": "N", "config": _config()}
    )
    _problem(resp, 422, "registry_config_not_deployed")
    assert rows(sync_engine, "SELECT * FROM registry_agents WHERE agent_id = :a", a=other) == []


def test_an_output_schema_for_another_contract_is_422(
    client: TestClient, sync_engine: Engine, test_manifest: str
) -> None:
    admin, _ = _admin(client)
    _register(client, admin, test_manifest)
    resp = client.post(
        f"{URL}/{test_manifest}/config-versions",
        headers={**admin, **_if_match(1)},
        json=_config(output_schema_version=2),
    )
    _problem(resp, 422, "registry_config_incompatible_contract")
    assert len(_version_rows(sync_engine, test_manifest)) == 1


def test_invalid_config_fields_are_422(client: TestClient, test_manifest: str) -> None:
    admin, _ = _admin(client)
    _register(client, admin, test_manifest)
    url = f"{URL}/{test_manifest}/config-versions"
    for overrides in (
        {"semver": "v1"},
        {"tool_permissions": ["write everything"]},
        {"prompt_version": 0},
        {"unknown": 1},
    ):
        _problem(
            client.post(url, headers={**admin, **_if_match(1)}, json=_config(**overrides)), 422
        )


def test_a_non_read_tool_permission_is_422_and_stores_nothing(
    client: TestClient, sync_engine: Engine, test_manifest: str
) -> None:
    """Story 5.4: only the ToolGateway's READ tools can be granted."""
    admin, _ = _admin(client)
    _register(client, admin, test_manifest)
    url = f"{URL}/{test_manifest}/config-versions"
    for grant in (["intake.requirement.edit"], ["gaps.gap.list", "estimates.estimate.export"]):
        resp = client.post(
            url, headers={**admin, **_if_match(1)}, json=_config(tool_permissions=grant)
        )
        _problem(resp, 422, "tool_permission_not_read_only")
    assert len(_version_rows(sync_engine, test_manifest)) == 1
    resp = client.post(
        URL,
        headers=admin,
        json={
            "agent_id": f"{test_manifest[:-6]}_two_agent",
            "name": "Second",
            "config": _config(tool_permissions=["knowledge.source.retire"]),
        },
    )
    _problem(resp, 422, "tool_permission_not_read_only")


def test_disable_eval_only_and_enable_with_if_match_and_trace(
    client: TestClient, sync_engine: Engine, test_manifest: str
) -> None:
    admin, admin_id = _admin(client)
    agent = _register(client, admin, test_manifest)
    version_id = agent["current_config"]["id"]
    url = f"{URL}/{test_manifest}/status"
    _problem(client.post(url, headers=admin, json={"status": "disabled"}), 428)
    _problem(client.post(url, headers={**admin, **_if_match(5)}, json={"status": "disabled"}), 412)
    _problem(client.post(url, headers={**admin, **_if_match(1)}, json={"status": "off"}), 422)
    disabled = client.post(url, headers={**admin, **_if_match(1)}, json={"status": "disabled"})
    assert disabled.status_code == 200, disabled.text
    assert (disabled.json()["status"], disabled.json()["row_version"]) == ("disabled", 2)
    same = client.post(url, headers={**admin, **_if_match(2)}, json={"status": "disabled"})
    assert (same.status_code, same.json()["row_version"]) == (200, 2)  # no-op
    eval_only = client.post(url, headers={**admin, **_if_match(2)}, json={"status": "eval_only"})
    assert eval_only.json()["status"] == "eval_only"
    enabled = client.post(url, headers={**admin, **_if_match(3)}, json={"status": "active"})
    assert enabled.json()["status"] == "active"
    events = _events(sync_engine, agent["id"])[1:]
    assert [e["event_type"] for e in events] == [
        "registry.agent.disabled",
        "registry.agent.disabled",
        "registry.agent.enabled",
    ]
    assert [(e["payload"]["from_status"], e["payload"]["to_status"]) for e in events] == [
        ("active", "disabled"),
        ("disabled", "eval_only"),
        ("eval_only", "active"),
    ]
    for event in events:
        assert (event["opportunity_id"], event["actor_id"]) == (None, str(admin_id))
        assert event["payload"]["from_config_version_id"] == version_id
        assert event["payload"]["to_config_version_id"] == version_id


def test_psa_app_cannot_edit_or_delete_versions_or_delete_agents(sync_engine: Engine) -> None:
    seeded = rules.seed_config_version_id("pm_agent")
    for statement in (
        "UPDATE registry_agent_config_versions SET semver = '9.9.9' WHERE id = :v",
        "DELETE FROM registry_agent_config_versions WHERE id = :v",
        "DELETE FROM registry_agents WHERE agent_id = 'pm_agent' AND :v IS NOT NULL",
        # Story 5.5: a Re-plan may re-pin a task's config version, nothing else of a pin.
        "UPDATE workflows_tasks SET agent = 'pm_agent' WHERE false AND :v IS NOT NULL",
    ):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(statement), {"v": seeded})


# --- disabled Agents in runs ---------------------------------------------------------------
# Story 5.5 (pause and resume): a disabled Agent's task is no longer skipped silently; the
# run waits for a person, who continues without it (the task then reads as skipped,
# `agent_disabled`). Pause and resume itself is covered in `test_workflows_decisions.py`.


def _continue_without(
    client: TestClient, headers: dict[str, str], opp_id: str, run_id: str, db_url: str
) -> None:
    """Resolve the waiting run's one open decision with Continue without, and resume it."""
    view = client.get(f"{BASE}/{opp_id}/assessments", headers=headers).json()
    assert view["run"]["status"] == "waiting_for_human"
    (decision,) = [d for d in view["run"]["decisions"] if d["status"] == "open"]
    resolved = client.post(
        f"{BASE}/{opp_id}/assessment-runs/{run_id}/decisions/{decision['id']}/resolve",
        headers={**headers, **_if_match(decision["row_version"])},
        json={"choice": "continue_without"},
    )
    assert resolved.status_code == 200, resolved.text
    assert drain(db_url, RESUME) == ["succeeded"]


def test_a_disabled_agents_task_waits_then_is_skipped_and_the_others_versions_pinned(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    restore_agents: None,
) -> None:
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    _set_status(client, admin, "security_agent", "disabled")
    fake = install(AgentGateway(replies()))

    body = started(client, headers, opp["id"])
    tasks = {t["agent"]: t for t in body["tasks"]}
    assert [tasks[a]["status"] for a in AGENTS] == ["queued"] * 3  # every task pinned
    assert drain(db_url, ASSESS) == ["succeeded"]
    assert task_rows(sync_engine, body["id"])["security_agent"]["status"] == "queued"
    _continue_without(client, headers, opp["id"], body["id"], db_url)
    assert task_rows(sync_engine, body["id"])["security_agent"]["skip_reason"] == "agent_disabled"
    # Continue without doesn't count against the run (Story 5.5, user decision 2026-10-24).
    (run,) = rows(sync_engine, "SELECT * FROM workflows_runs WHERE id = :r", r=body["id"])
    assert run["status"] == "succeeded"

    assert {r.caller.agent_id for r in fake.requests} == {
        "engineering_agent",
        "pm_agent",
        "critic_agent",  # Story 6.4: it reviews the two Assessments
    }
    pinned = task_rows(sync_engine, body["id"])
    for request in fake.requests:
        assert request.caller.config_version == str(
            pinned[request.caller.agent_id]["config_version_id"]
        )
    for agent in ("engineering_agent", "pm_agent"):
        (stored,) = assessment_rows(sync_engine, opp["id"], agent)
        assert stored["config_version_id"] == pinned[agent]["config_version_id"]
        version = rows(
            sync_engine,
            "SELECT * FROM registry_agent_config_versions WHERE id = :v",
            v=stored["config_version_id"],
        )[0]
        assert (version["agent_id"], version["semver"], version["model_digest"]) == (
            agent,
            "0.1.0",
            "unpinned",
        )
        assert version["prompt_version"] == 1
    assert assessment_rows(sync_engine, opp["id"], "security_agent") == []
    (skipped,) = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = 'assessments.task.skipped'",
        o=opp["id"],
    )
    assert (skipped["actor_type"], skipped["payload"]["agent"]) == ("system", "security_agent")
    assert skipped["payload"]["reason"] == "agent_disabled"
    assert skipped["payload"]["config_version_id"] == str(
        pinned["security_agent"]["config_version_id"]
    )
    view = client.get(f"{BASE}/{opp['id']}/assessments", headers=headers).json()
    (security,) = [t for t in view["run"]["tasks"] if t["agent"] == "security_agent"]
    assert security["skip_reason"] == "agent_disabled"
    assessed = {a["agent"]: a["assessment"] for a in view["assessments"]}
    assert assessed["pm_agent"]["config_version_id"] == str(pinned["pm_agent"]["config_version_id"])


def test_an_agent_disabled_while_its_task_is_queued_waits_at_job_start(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    restore_agents: None,
) -> None:
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    assert [t["status"] for t in body["tasks"]] == ["queued"] * (len(AGENTS) + 1)
    _set_status(client, admin, "pm_agent", "eval_only")
    assert drain(db_url, ASSESS) == ["succeeded"]
    assert task_rows(sync_engine, body["id"])["pm_agent"]["status"] == "queued"
    _continue_without(client, headers, opp["id"], body["id"], db_url)
    tasks = task_rows(sync_engine, body["id"])
    assert (tasks["pm_agent"]["status"], tasks["pm_agent"]["skip_reason"]) == (
        "skipped",
        "agent_disabled",
    )
    assert tasks["engineering_agent"]["status"] == "succeeded"
    assert fake.calls("pm_agent") == 0
    (run,) = rows(sync_engine, "SELECT * FROM workflows_runs WHERE id = :r", r=body["id"])
    assert run["status"] == "succeeded"  # the chosen skip doesn't count against it
    (skipped,) = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type = 'assessments.task.skipped'",
        o=opp["id"],
    )
    assert (skipped["actor_type"], skipped["payload"]["agent"]) == ("system", "pm_agent")
    # A skipped task is not a failed one: retrying it is refused as such.
    retried = client.post(
        f"{BASE}/{opp['id']}/assessment-runs/{body['id']}/tasks/pm_agent/retry", headers=headers
    )
    _problem(retried, 409, "assessment_task_not_failed")


def test_retrying_a_failed_task_of_a_disabled_agent_is_409(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    restore_agents: None,
) -> None:
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(
        AgentGateway(
            replies(security_agent=[ModelUnavailableError("down", error_code="connection")])
        )
    )
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    assert task_rows(sync_engine, body["id"])["security_agent"]["status"] == "failed"
    _set_status(client, admin, "security_agent", "disabled")
    retried = client.post(
        f"{BASE}/{opp['id']}/assessment-runs/{body['id']}/tasks/security_agent/retry",
        headers=headers,
    )
    assert _problem(retried, 409, "registry_agent_disabled")["detail"] == (
        "Security Agent is disabled"
    )
    task = task_rows(sync_engine, body["id"])["security_agent"]
    assert (task["status"], task["error_code"]) == ("failed", "model_unavailable")


def test_a_run_keeps_the_version_it_pinned_when_a_new_one_is_created(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: Any
) -> None:
    admin, _ = _admin(client)
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(replies()))
    body = started(client, headers, opp["id"])
    before = task_rows(sync_engine, body["id"])["engineering_agent"]["config_version_id"]
    current = client.get(f"{URL}/engineering_agent", headers=admin).json()
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
        f"{URL}/engineering_agent/config-versions",
        headers={**admin, **_if_match(current["row_version"])},
        json=same,
    )
    assert created.status_code == 201, created.text
    after = UUID(created.json()["current_config"]["id"])
    assert after != before
    assert drain(db_url, ASSESS) == ["succeeded"]
    (stored,) = assessment_rows(sync_engine, opp["id"], "engineering_agent")
    assert stored["config_version_id"] == before
    (call,) = [r for r in fake.requests if r.caller.agent_id == "engineering_agent"]
    assert call.caller.config_version == str(before)
    # The next run pins the new current version.
    body = started(client, headers, opp["id"])
    assert task_rows(sync_engine, body["id"])["engineering_agent"]["config_version_id"] == after


def test_a_disabled_single_agent_step_is_409_and_its_queued_job_fails(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    restore_agents: None,
) -> None:
    admin, _ = _admin(client)
    headers, opp = extracted(client, sync_engine, db_url, gateway)  # its detection is queued
    calls = len(gateway.requests)
    _set_status(client, admin, "clarification_agent", "disabled")
    assert drain(db_url, DETECT) == ["succeeded"]
    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["error_code"]) == ("failed", "registry_agent_disabled")
    assert len(gateway.requests) == calls  # no model call

    retried = client.post(f"{BASE}/{opp['id']}/gap-detections", headers=headers)
    body = _problem(retried, 409, "registry_agent_disabled")
    assert body["detail"] == "Clarification Agent is disabled"
    assert len(detections(sync_engine, opp["id"])) == 1  # nothing queued

    for path, agent in (
        ("red-team-reviews", "red_team_agent"),
        ("estimate-drafts", "estimating_agent"),
        ("extractions", "intake_agent"),
    ):
        _set_status(client, admin, agent, "disabled")
        resp = client.post(f"{BASE}/{opp['id']}/{path}", headers=headers)
        _problem(resp, 409, "registry_agent_disabled")


def test_an_import_is_refused_while_its_agent_is_disabled(
    client: TestClient, sync_engine: Engine, restore_agents: None
) -> None:
    admin, _ = _admin(client)
    engineer, user_id = _signed_in(client, "Importer", "presales_engineer")
    _set_status(client, admin, "opportunity_intake_agent", "disabled")
    resp = client.post(
        "/api/v1/opportunity-imports",
        headers=engineer,
        files={"file": ("call.txt", b"Meridian Fresh Foods wants a WMS.", "text/plain")},
    )
    body = _problem(resp, 409, "registry_agent_disabled")
    assert body["detail"] == "Opportunity Intake Agent is disabled"
    assert (
        rows(sync_engine, "SELECT * FROM opportunities_imports WHERE uploaded_by = :u", u=user_id)
        == []
    )


def test_a_queued_job_fails_when_its_agent_was_disabled_meanwhile(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    restore_agents: None,
) -> None:
    """Each single-agent job: queued while its agent is active, the agent disabled, then the
    job runs: it ends without a model call and its row is failed / `registry_agent_disabled`."""
    admin, _ = _admin(client)

    def disabled_run(agent: str, job: str) -> int:
        calls = len(gateway.requests)
        _set_status(client, admin, agent, "disabled")
        # Earlier Opportunities of this test may have a job of the same type waiting too.
        assert set(drain(db_url, job)) == {"succeeded"}
        assert len(gateway.requests) == calls  # no model call
        _set_status(client, admin, agent, "active")
        return calls

    def failed(table: str, opp_id: str) -> None:
        (row,) = rows(
            sync_engine,
            f"SELECT * FROM {table} WHERE opportunity_id = :o ORDER BY created_at DESC LIMIT 1",
            o=opp_id,
        )
        assert (row["status"], row["error_code"]) == ("failed", "registry_agent_disabled")

    # Requirement extraction (queued once its Source is parsed).
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"{detection_tests.NOTE}{uuid4()}"))
    disabled_run("intake_agent", EXTRACT)
    failed("intake_extractions", opp["id"])

    # Estimate draft.
    _, opp = draft_tests.detected(client, sync_engine, db_url, gateway)  # its draft is queued
    disabled_run("estimating_agent", DRAFT)
    failed("estimates_drafts", opp["id"])

    # Red Team review (queued by the accepted draft).
    _, opp = red_team_drafted(client, sync_engine, db_url, gateway)
    disabled_run("red_team_agent", RED_TEAM)
    failed("assessments_red_team_runs", opp["id"])

    # Assumption proposals: no error code column; they are marked failed.
    _, opp = assumption_tests.drafted(client, sync_engine, db_url, gateway)
    disabled_run("estimating_agent", PROPOSE)
    (version,) = draft_tests.versions(sync_engine, opp["id"])
    assert version["proposal_status"] == "failed"


def test_a_queued_import_fails_when_its_agent_was_disabled_meanwhile(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: Any,
    restore_agents: None,
    monkeypatch: pytest.MonkeyPatch,
    storage_dir: Path,
) -> None:
    admin, _ = _admin(client)
    engineer, _ = _signed_in(client, "Importer", "presales_engineer")
    real_enqueue = imports.enqueue

    async def hidden_enqueue(uow: Any, payload: Any, **kwargs: Any) -> UUID:
        kwargs["run_after"] = datetime.now(UTC) + HIDDEN  # no other claimer takes it
        return await real_enqueue(uow, payload, **kwargs)

    monkeypatch.setattr(imports, "enqueue", hidden_enqueue)
    import_tests.MY_IMPORTS.clear()
    try:
        note = f"Notes {uuid4()}".encode()
        created = import_tests._import(client, engineer, "notes.txt", note)
        _set_status(client, admin, "opportunity_intake_agent", "disabled")
        assert import_tests.drain_imports(db_url) == ["succeeded"]
        row = import_tests.import_row(sync_engine, created["id"])
        assert (row["status"], row["error_code"]) == ("failed", "registry_agent_disabled")
        assert gateway.requests == []
    finally:
        import_tests.MY_IMPORTS.clear()


def test_a_prompt_version_missing_a_named_prompt_file_is_422_not_deployed(
    client: TestClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`estimating_agent` also reads `v<N>-assumptions.md`: `v2.md` alone is not prompt v2."""
    data = json.loads(json.dumps(dict(deployed.load().data)))
    data["prompts"]["estimating_agent"]["2"] = {"v2.md": "0" * 64}
    manifest = deployed.Manifest(data)
    monkeypatch.setattr(deployed, "load", lambda: manifest)
    assert not manifest.has_prompt("estimating_agent", 2)
    assert manifest.has_prompt("estimating_agent", 1)

    admin, _ = _admin(client)
    current = client.get(f"{URL}/estimating_agent", headers=admin).json()
    before = len(_version_rows(sync_engine, "estimating_agent"))
    resp = client.post(
        f"{URL}/estimating_agent/config-versions",
        headers={**admin, **_if_match(current["row_version"])},
        json=_config(semver="0.1.0", model_profile="demo-chat", prompt_version=2),
    )
    _problem(resp, 422, "registry_config_not_deployed")
    assert len(_version_rows(sync_engine, "estimating_agent")) == before
