"""Admin-managed chat model profiles against a real, migrated Postgres as psa_app: the spec's
I/O matrix (create, not approved, duplicate, test passes, test fails, pin an unverified
profile, retire in use, non-admin, retired old run), the allowlist, the grants, the trace
events, and that a stored profile reaches the provider through the worker's real gateway.

Names and allowlist entries are unique per test: the tables are shared by every test.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import httpx
import httpx2
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.agents import manifest as deployed
from app.modules.registry.application import public as registry
from app.modules.registry.application.jobs import TEST_AGENT_ID, TEST_PROFILE, ProbeReply
from app.modules.registry.domain import model_profiles as rules
from app.modules.registry.domain.registry import SEED_NAMESPACE
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import queue as q
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.model_gateway import provider
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import (
    CallerMetadata,
    Message,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredRequest,
)
from app.platform.model_gateway.profiles import STRUCTURED_TEMPERATURE, UnknownModelProfileError
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import FakeGateway
from tests.test_intake_parse_job import _alembic
from tests.test_model_gateway import SEEDED
from tests.test_registry import (
    URL as AGENTS_URL,
)
from tests.test_registry import (
    _config,
    _events,
    _if_match,
    _register,
    test_manifest,  # noqa: F401 - a fixture
)
from tests.test_role_admin import _admin, _signed_in

storage_dir = extraction_tests.storage_dir
gateway = extraction_tests.gateway
client = extraction_tests.client

URL = "/api/v1/registry/model-profiles"
APPROVED_URL = "/api/v1/registry/approved-models"
BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations" / "versions"
MIGRATIONS = (
    VERSIONS / "20261102_0061_registry_model_profiles.py",
    VERSIONS / "20261102_0062_anthropic_custom_profiles.py",
)
SEED_MIGRATION = VERSIONS / "20261102_0063_seed_chat_profiles.py"
BEFORE_ANTHROPIC = "0061_registry_model_profiles"
BEFORE_SEED = "0062_anthropic_custom_profiles"
LEASE = LeaseSettings(lease_s=30, heartbeat_s=5)
MODEL = "gpt-oss:120b-cloud"
CLAUDE = "claude-opus-5-5"
CLAUDE_SONNET = "claude-sonnet-5-5"


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return _admin(client)[0]


def _name() -> str:
    return f"t-{uuid4().hex[:12]}"


def _form(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": _name(),
        "provider": "ollama",
        "model": MODEL,
        "num_ctx": 20000,
        "temperature": 0.3,
    }
    return {**body, **overrides}


def _create(client: TestClient, admin: dict[str, str], **overrides: Any) -> dict[str, Any]:
    resp = client.post(URL, json=_form(**overrides), headers=admin)
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _listed(client: TestClient, admin: dict[str, str], profile_id: str) -> dict[str, Any]:
    resp = client.get(URL, headers=admin)
    assert resp.status_code == 200, resp.text
    found: dict[str, Any] = next(p for p in resp.json()["items"] if p["id"] == profile_id)
    return found


def _test_jobs(db_url: str) -> list[str]:
    """Run every queued `registry.test_model_profile` job; retries run at once."""

    async def scenario() -> list[str]:
        engine = create_engine(Settings(database_url=db_url))
        outcomes: list[str] = []
        try:
            for _ in range(50):
                job = await q.claim(engine, owner="test", lease_s=30, job_types=(TEST_PROFILE,))
                if job is None:
                    break
                outcomes.append(await run_job(engine, job, LEASE))
        finally:
            await engine.dispose()
        return outcomes

    return run_async(scenario())


def _verified(
    client: TestClient,
    admin: dict[str, str],
    db_url: str,
    gateway: FakeGateway,
    **overrides: Any,
) -> dict[str, Any]:
    gateway.replies = [ProbeReply(status="ok")]
    profile = _create(client, admin, **overrides)
    _test_jobs(db_url)
    return _listed(client, admin, profile["id"])


def _new_version(
    client: TestClient,
    admin: dict[str, str],
    agent: dict[str, Any],
    profile: str,
    *,
    semver: str = "0.3.0",
) -> Any:
    return client.post(
        f"{AGENTS_URL}/{agent['agent_id']}/config-versions",
        json={**_config(model_profile=profile, semver=semver), "reason": "A test."},
        headers={**admin, **_if_match(agent["row_version"])},
    )


# --- rules ----------------------------------------------------------------------------------


def test_the_allowlist_seed_covers_the_seeded_profiles_models() -> None:
    source = "".join(path.read_text(encoding="utf-8") for path in MIGRATIONS)
    for profile in SEEDED.values():
        assert f'("{profile.provider}", "{profile.model}")' in source


def test_temperature_and_reasoning_effort_are_mutually_exclusive() -> None:
    assert rules.sampling("ollama", None, None) == (0.1, None)
    assert rules.sampling("ollama", 0.4, None) == (0.4, None)
    assert rules.sampling("openai", None, "low") == (None, "low")
    with pytest.raises(ValueError, match="not both"):
        rules.sampling("openai", 0.4, "low")
    with pytest.raises(ValueError, match="`openai` or `anthropic`"):
        rules.sampling("ollama", None, "low")


def test_a_claude_profile_uses_a_reasoning_effort_never_a_temperature() -> None:
    assert rules.sampling("anthropic", None, "high") == (None, "high")
    assert rules.sampling("anthropic", None, None) == (None, "medium")
    for effort in (None, "low"):
        with pytest.raises(ValueError, match="reasoning effort"):
            rules.sampling("anthropic", 0.4, effort)


def _stored(provider_name: rules.CustomProvider, model: str) -> rules.CustomProfile:
    return rules.CustomProfile(
        id=uuid4(),
        name="reasoner",
        provider=provider_name,
        model=model,
        num_ctx=20000,
        temperature=None,
        reasoning_effort="high",
        state=rules.ProfileState.VERIFIED,
        error_code=None,
        latency_ms=None,
        tested_at=None,
        created_by=None,
        created_at=datetime.now(UTC),
    )


def test_a_reasoning_profile_becomes_a_gateway_profile_without_its_own_temperature() -> None:
    definition = _stored("openai", "gpt-4.1-mini").definition
    assert (definition.provider, definition.reasoning_effort) == ("openai", "high")
    assert (definition.model, definition.num_ctx) == ("gpt-4.1-mini", 20000)
    assert definition.temperature == STRUCTURED_TEMPERATURE
    assert definition.refusal_fallback is False


def test_a_claude_profile_is_defined_like_the_seeded_one() -> None:
    definition = _stored("anthropic", CLAUDE).definition
    seeded = SEEDED["anthropic-opus-chat"]
    assert (definition.provider, definition.reasoning_effort) == ("anthropic", "high")
    assert definition.refusal_fallback is seeded.refusal_fallback is True
    assert definition.max_tokens == seeded.max_tokens == 16000


def test_the_manifest_holds_no_profile() -> None:
    assert "profiles" not in deployed.load().data
    assert "profiles" not in deployed.build()


# --- create ---------------------------------------------------------------------------------


def test_create_stores_an_untested_row_queues_its_test_and_traces(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    profile = _create(client, admin)

    assert profile["state"] == "untested"
    assert profile["model"] == MODEL
    assert profile["num_ctx"] == 20000
    assert profile["temperature"] == 0.3
    assert profile["reasoning_effort"] is None
    jobs = rows(
        sync_engine,
        "SELECT status FROM platform_jobs WHERE job_type = :t AND payload->>'profile_id' = :p",
        t=TEST_PROFILE,
        p=profile["id"],
    )
    assert [j["status"] for j in jobs] == ["queued"]
    (event,) = _events(sync_engine, profile["id"])
    assert event["event_type"] == "registry.model_profile.created"
    assert event["payload"]["name"] == profile["name"]
    assert event["opportunity_id"] is None


def test_a_queued_test_shows_as_untested_not_failed(
    client: TestClient, admin: dict[str, str]
) -> None:
    profile = _create(client, admin)
    assert _listed(client, admin, profile["id"])["state"] == "untested"


def test_a_model_off_the_allowlist_stores_nothing(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    name = _name()
    resp = client.post(URL, json=_form(name=name, model="gpt-9"), headers=admin)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "registry_model_not_approved")
    assert rows(sync_engine, "SELECT 1 FROM registry_model_profiles WHERE name = :n", n=name) == []


def test_a_model_approved_for_another_provider_is_not_approved(
    client: TestClient, admin: dict[str, str]
) -> None:
    resp = client.post(URL, json=_form(provider="openai"), headers=admin)
    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "registry_model_not_approved")


@pytest.mark.parametrize("taken", ["custom", *SEEDED])
def test_a_duplicate_name_stores_nothing(
    client: TestClient, admin: dict[str, str], sync_engine: Engine, taken: str
) -> None:
    name = _create(client, admin)["name"] if taken == "custom" else taken
    count = "SELECT count(*) AS n FROM registry_model_profiles WHERE name = :n"
    before = rows(sync_engine, count, n=name)[0]["n"]

    resp = client.post(URL, json=_form(name=name), headers=admin)

    assert resp.status_code == 409, resp.text
    assert_problem(resp.json(), 409, "registry_model_profile_duplicate")
    assert rows(sync_engine, count, n=name)[0]["n"] == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "Has Spaces"},
        {"name": "x" * 65},
        {"provider": "azure"},
        {"num_ctx": 1000},
        {"temperature": 3},
        {"reasoning_effort": "extreme", "temperature": None},
        {"temperature": 0.2, "reasoning_effort": "low", "provider": "openai"},
        {"reasoning_effort": "low", "temperature": None},  # provider ollama
    ],
)
def test_an_invalid_form_is_a_422(
    client: TestClient, admin: dict[str, str], overrides: dict[str, Any]
) -> None:
    resp = client.post(URL, json=_form(**overrides), headers=admin)
    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")


@pytest.mark.parametrize("field", ["base_url", "api_key"])
def test_the_form_takes_no_endpoint_or_secret(
    client: TestClient, admin: dict[str, str], field: str
) -> None:
    resp = client.post(URL, json=_form(**{field: "x"}), headers=admin)
    assert resp.status_code == 422, resp.text


def test_a_reasoning_profile_stores_no_temperature(
    client: TestClient, admin: dict[str, str]
) -> None:
    profile = _create(
        client,
        admin,
        provider="openai",
        model="gpt-4.1-mini",
        temperature=None,
        reasoning_effort="medium",
    )
    assert profile["temperature"] is None
    assert profile["reasoning_effort"] == "medium"


def _claude(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "provider": "anthropic",
        "model": CLAUDE,
        "temperature": None,
        "reasoning_effort": "high",
    }
    return {**fields, **overrides}


def test_a_claude_profile_stores_its_effort_and_queues_its_test(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    profile = _create(client, admin, **_claude())

    assert profile["provider"] == "anthropic"
    assert profile["state"] == "untested"
    assert profile["temperature"] is None
    assert profile["reasoning_effort"] == "high"
    jobs = rows(
        sync_engine,
        "SELECT status FROM platform_jobs WHERE job_type = :t AND payload->>'profile_id' = :p",
        t=TEST_PROFILE,
        p=profile["id"],
    )
    assert [j["status"] for j in jobs] == ["queued"]


def test_both_seeded_claude_models_can_be_used(client: TestClient, admin: dict[str, str]) -> None:
    profile = _create(client, admin, **_claude(model=CLAUDE_SONNET))
    assert profile["model"] == CLAUDE_SONNET


def test_a_claude_profile_defaults_an_omitted_effort(
    client: TestClient, admin: dict[str, str]
) -> None:
    body = _form(provider="anthropic", model=CLAUDE)
    del body["temperature"]

    resp = client.post(URL, json=body, headers=admin)

    assert resp.status_code == 201, resp.text
    assert resp.json()["temperature"] is None
    assert resp.json()["reasoning_effort"] == "medium"


def test_a_temperature_on_a_claude_profile_stores_nothing(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    name = _name()
    body = _form(name=name, **_claude(temperature=0.3, reasoning_effort=None))

    resp = client.post(URL, json=body, headers=admin)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert "Claude profiles use a reasoning effort" in resp.json()["detail"]
    assert rows(sync_engine, "SELECT 1 FROM registry_model_profiles WHERE name = :n", n=name) == []


def test_an_unapproved_claude_model_stores_nothing(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    name = _name()
    body = _form(name=name, **_claude(model="claude-unlisted"))

    resp = client.post(URL, json=body, headers=admin)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "registry_model_not_approved")
    assert rows(sync_engine, "SELECT 1 FROM registry_model_profiles WHERE name = :n", n=name) == []


def test_an_effort_on_ollama_stores_nothing_and_names_both_providers(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    name = _name()
    body = _form(name=name, temperature=None, reasoning_effort="low")

    resp = client.post(URL, json=body, headers=admin)

    assert resp.status_code == 422, resp.text
    assert "`openai`" in resp.json()["detail"]
    assert "`anthropic`" in resp.json()["detail"]
    assert rows(sync_engine, "SELECT 1 FROM registry_model_profiles WHERE name = :n", n=name) == []


def test_a_claude_model_can_be_added_to_the_allowlist(
    client: TestClient, admin: dict[str, str]
) -> None:
    model = f"claude-{uuid4().hex[:10]}"
    added = client.post(APPROVED_URL, json={"provider": "anthropic", "model": model}, headers=admin)
    assert added.status_code == 201, added.text
    assert _create(client, admin, **_claude(model=model))["model"] == model


# --- the live test --------------------------------------------------------------------------


def test_a_passing_test_verifies_the_profile_and_keeps_no_reply(
    client: TestClient,
    admin: dict[str, str],
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
) -> None:
    gateway.replies = [ProbeReply(status="ok")]
    profile = _create(client, admin)

    assert "succeeded" in _test_jobs(db_url)

    found = _listed(client, admin, profile["id"])
    assert found["state"] == "verified"
    assert found["error_code"] is None
    assert found["latency_ms"] >= 0
    assert found["tested_at"] is not None
    request = next(r for r in gateway.requests if r.profile == profile["name"])
    assert request.priority == "interactive"
    assert request.caller.agent_id == TEST_AGENT_ID
    _, tested = _events(sync_engine, profile["id"])
    assert tested["event_type"] == "registry.model_profile.tested"
    assert set(tested["payload"]) == {"profile_id", "name", "state", "error_code", "latency_ms"}
    assert tested["actor_id"] == TEST_PROFILE


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ModelTimeoutError("slow"), "timeout"),
        (ModelUnavailableError("no", error_code="http_404"), "http_404"),
        (ModelOutputInvalidError("bad"), "invalid_output"),
    ],
)
def test_a_failing_test_marks_the_profile_failed_and_can_be_retested(
    client: TestClient,
    admin: dict[str, str],
    db_url: str,
    gateway: FakeGateway,
    failure: Exception,
    code: str,
) -> None:
    gateway.replies = [failure]
    profile = _create(client, admin)

    _test_jobs(db_url)  # a model error is the result, not a job failure

    found = _listed(client, admin, profile["id"])
    assert (found["state"], found["error_code"]) == ("failed", code)

    resp = client.post(f"{URL}/{profile['id']}/test", headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "untested"
    assert resp.json()["error_code"] is None

    gateway.replies = [ProbeReply(status="ok")]
    _test_jobs(db_url)
    assert _listed(client, admin, profile["id"])["state"] == "verified"


def test_a_verified_profile_cannot_be_retested(
    client: TestClient, admin: dict[str, str], db_url: str, gateway: FakeGateway
) -> None:
    profile = _verified(client, admin, db_url, gateway)
    resp = client.post(f"{URL}/{profile['id']}/test", headers=admin)
    assert resp.status_code == 409, resp.text
    assert_problem(resp.json(), 409, "registry_model_profile_not_retestable")


def test_an_untested_profile_can_be_retested_and_its_extra_job_is_harmless(
    client: TestClient, admin: dict[str, str], db_url: str, gateway: FakeGateway
) -> None:
    gateway.replies = [ProbeReply(status="ok")]
    profile = _create(client, admin)

    resp = client.post(f"{URL}/{profile['id']}/test", headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "untested"

    _test_jobs(db_url)
    assert _listed(client, admin, profile["id"])["state"] == "verified"
    assert len([r for r in gateway.requests if r.profile == profile["name"]]) == 1


def test_a_crash_on_every_attempt_ends_failed(
    client: TestClient,
    admin: dict[str, str],
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
) -> None:
    gateway.replies = [RuntimeError("boom")]
    profile = _create(client, admin)

    for _ in range(3):  # the job's attempts; each retry waits out its backoff here
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE platform_jobs SET run_after = now() WHERE job_type = :t"),
                {"t": TEST_PROFILE},
            )
        _test_jobs(db_url)

    found = _listed(client, admin, profile["id"])
    assert (found["state"], found["error_code"]) == ("failed", "test_error")


def test_a_redelivered_job_changes_nothing(
    client: TestClient, admin: dict[str, str], db_url: str, gateway: FakeGateway
) -> None:
    profile = _verified(client, admin, db_url, gateway)
    calls = len(gateway.requests)

    async def enqueue_again() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            from app.modules.registry.application.jobs import enqueue_profile_test
            from app.platform.uow import unit_of_work

            async with unit_of_work(engine) as uow:
                await enqueue_profile_test(uow, UUID(profile["id"]))
        finally:
            await engine.dispose()

    run_async(enqueue_again())
    gateway.replies = [ModelTimeoutError("slow")]
    _test_jobs(db_url)

    assert len(gateway.requests) == calls
    assert _listed(client, admin, profile["id"])["state"] == "verified"


def test_a_profile_retired_during_its_test_stays_retired(
    client: TestClient, admin: dict[str, str], db_url: str
) -> None:
    fake = FakeGateway()

    def retire_mid_call(_: StructuredRequest[Any]) -> ProbeReply:
        resp = client.post(f"{URL}/{profile['id']}/retire", headers=admin)
        assert resp.status_code == 200, resp.text
        return ProbeReply(status="ok")

    fake.replies = [retire_mid_call]
    provider.install(fake)
    try:
        profile = _create(client, admin)
        _test_jobs(db_url)
    finally:
        provider.install(None)
    assert _listed(client, admin, profile["id"])["state"] == "retired"


# --- pinning --------------------------------------------------------------------------------


def test_a_verified_profile_is_offered_and_can_be_pinned(
    client: TestClient,
    admin: dict[str, str],
    db_url: str,
    gateway: FakeGateway,
    test_manifest: str,  # noqa: F811
) -> None:
    profile = _verified(client, admin, db_url, gateway)
    agent = _register(client, admin, test_manifest)

    options = client.get(f"{AGENTS_URL}/{test_manifest}/config-options", headers=admin).json()
    assert profile["name"] in options["model_profiles"]
    assert options["model_profiles"] == sorted(options["model_profiles"])

    resp = _new_version(client, admin, agent, profile["name"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["current_config"]["model_profile"] == profile["name"]
    assert resp.json()["effective_model"] == {"profile": profile["name"], "model": MODEL}


@pytest.mark.parametrize("state", ["untested", "failed", "retired"])
def test_pinning_an_unverified_profile_stores_nothing(
    client: TestClient,
    admin: dict[str, str],
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    test_manifest: str,  # noqa: F811
    state: str,
) -> None:
    gateway.replies = [ModelTimeoutError("slow")]
    profile = _create(client, admin)
    if state != "untested":
        _test_jobs(db_url)
    if state == "retired":
        client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    agent = _register(client, admin, test_manifest)

    options = client.get(f"{AGENTS_URL}/{test_manifest}/config-options", headers=admin).json()
    assert profile["name"] not in options["model_profiles"]

    resp = _new_version(client, admin, agent, profile["name"])
    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "registry_config_not_deployed")
    assert f"is {state}" in resp.json()["detail"]
    assert "manifest" not in resp.json()["detail"]
    versions = rows(
        sync_engine,
        "SELECT 1 FROM registry_agent_config_versions WHERE agent_id = :a",
        a=test_manifest,
    )
    assert len(versions) == 1


def test_retiring_a_profile_an_agent_pins_changes_nothing(
    client: TestClient,
    admin: dict[str, str],
    db_url: str,
    gateway: FakeGateway,
    test_manifest: str,  # noqa: F811
) -> None:
    profile = _verified(client, admin, db_url, gateway)
    agent = _register(client, admin, test_manifest)
    pinned = _new_version(client, admin, agent, profile["name"]).json()

    resp = client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    assert resp.status_code == 409, resp.text
    assert_problem(resp.json(), 409, "registry_model_profile_in_use")
    assert _listed(client, admin, profile["id"])["state"] == "verified"

    moved = _new_version(client, admin, pinned, "openai-chat", semver="0.4.0")
    assert moved.status_code == 201, moved.text
    retired = client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    assert retired.status_code == 200, retired.text
    assert retired.json()["state"] == "retired"

    again = client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    assert again.status_code == 200, again.text


def test_retire_is_traced_and_an_unknown_profile_is_a_404(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    profile = _create(client, admin)
    client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    types = [e["event_type"] for e in _events(sync_engine, profile["id"])]
    assert "registry.model_profile.retired" in types

    resp = client.post(f"{URL}/{uuid4()}/retire", headers=admin)
    assert resp.status_code == 404, resp.text


def test_retiring_twice_traces_once(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    profile = _create(client, admin)
    client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    client.post(f"{URL}/{profile['id']}/retire", headers=admin)
    retired = [
        e
        for e in _events(sync_engine, profile["id"])
        if e["event_type"] == "registry.model_profile.retired"
    ]
    assert len(retired) == 1


def test_the_agent_routes_show_a_custom_profiles_model(
    client: TestClient,
    admin: dict[str, str],
    db_url: str,
    gateway: FakeGateway,
    test_manifest: str,  # noqa: F811
) -> None:
    profile = _verified(client, admin, db_url, gateway)
    expected = {"profile": profile["name"], "model": MODEL}
    resp = client.post(
        AGENTS_URL,
        headers=admin,
        json={
            "agent_id": test_manifest,
            "name": "Test Agent",
            "config": _config(model_profile=profile["name"]),
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["effective_model"] == expected

    one = client.get(f"{AGENTS_URL}/{test_manifest}", headers=admin)
    assert one.json()["effective_model"] == expected
    listed = client.get(AGENTS_URL, headers=admin).json()["items"]
    agent = next(a for a in listed if a["agent_id"] == test_manifest)
    assert agent["effective_model"] == expected


def test_a_verified_claude_profile_can_be_pinned(
    client: TestClient,
    admin: dict[str, str],
    db_url: str,
    gateway: FakeGateway,
    test_manifest: str,  # noqa: F811
) -> None:
    profile = _verified(client, admin, db_url, gateway, **_claude())
    assert profile["state"] == "verified"
    agent = _register(client, admin, test_manifest)

    resp = _new_version(client, admin, agent, profile["name"])

    assert resp.status_code == 201, resp.text
    assert resp.json()["effective_model"] == {"profile": profile["name"], "model": CLAUDE}


# --- resolving ------------------------------------------------------------------------------


def _ollama_reply(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/api/chat"):
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps({"status": "ok"})},
                "done_reason": "stop",
                "prompt_eval_count": 1,
                "eval_count": 1,
            },
        )
    return httpx.Response(404)


def _gateway_call(db_url: str, name: str) -> list[dict[str, Any]]:
    """One call of the profile through a real gateway with the worker's resolver; the
    bodies of the chat requests that reached the (mocked) provider."""
    sent: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat"):
            sent.append(json.loads(request.content))
        return _ollama_reply(request)

    async def scenario() -> None:
        settings = Settings(database_url=db_url)
        engine = create_engine(settings)
        try:
            async with ModelGateway(
                settings,
                engine,
                transport=httpx.MockTransport(transport),
                resolve_profile=registry.profile_resolver(engine),
            ) as models:
                await models.complete_structured(
                    StructuredRequest(
                        messages=[Message(role="user", content="fixed")],
                        output_model=ProbeReply,
                        caller=CallerMetadata(agent_id="pm_agent", config_version="1"),
                        profile=name,
                    )
                )
        finally:
            await engine.dispose()

    run_async(scenario())
    return sent


def test_a_run_uses_the_stored_definition_and_records_the_profile(
    client: TestClient,
    admin: dict[str, str],
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
) -> None:
    profile = _verified(client, admin, db_url, gateway, num_ctx=24000, temperature=0.7)

    (body,) = _gateway_call(db_url, profile["name"])

    assert body["model"] == MODEL
    assert body["options"] == {"temperature": 0.7, "num_ctx": 24000}
    calls = rows(
        sync_engine,
        "SELECT model FROM platform_model_calls WHERE profile = :p",
        p=profile["name"],
    )
    assert [c["model"] for c in calls] == [MODEL]


def _anthropic_reply() -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_stub",
            "type": "message",
            "role": "assistant",
            "model": CLAUDE,
            "content": [{"type": "text", "text": json.dumps({"status": "ok"})}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def _drain_stale_tests(db_url: str) -> None:
    """Run the live tests earlier tests left queued, on a fake: the queue is shared, and the
    real gateway below must see only the profile under test."""
    fake = FakeGateway()
    fake.replies = [ProbeReply(status="ok")]
    provider.install(fake)
    try:
        _test_jobs(db_url)
    finally:
        provider.install(None)


def _test_with_real_gateway(db_url: str, api_key: str | None) -> list[dict[str, Any]]:
    """Run the queued live tests the way the worker does: its gateway and resolver, with the
    Anthropic SDK's transport stubbed. The bodies of the requests that reached it."""
    sent: list[dict[str, Any]] = []

    def transport(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return _anthropic_reply()

    async def scenario() -> None:
        settings = Settings(database_url=db_url, anthropic_api_key=api_key)
        engine = create_engine(settings)
        try:
            async with ModelGateway(
                settings,
                engine,
                anthropic_transport=httpx2.MockTransport(transport),
                resolve_profile=registry.profile_resolver(engine),
            ) as models:
                provider.install(models)
                try:
                    for _ in range(50):
                        job = await q.claim(
                            engine, owner="test", lease_s=30, job_types=(TEST_PROFILE,)
                        )
                        if job is None:
                            break
                        await run_job(engine, job, LEASE)
                finally:
                    provider.install(None)
        finally:
            await engine.dispose()

    run_async(scenario())
    return sent


def test_a_claude_profile_reaches_the_anthropic_adapter_with_its_effort(
    client: TestClient,
    admin: dict[str, str],
    sync_engine: Engine,
    db_url: str,
) -> None:
    _drain_stale_tests(db_url)
    profile = _create(client, admin, **_claude(reasoning_effort="low"))

    (body,) = _test_with_real_gateway(db_url, "sk-ant-test")

    assert _listed(client, admin, profile["id"])["state"] == "verified"
    assert body["model"] == CLAUDE
    assert body["output_config"]["effort"] == "low"
    assert body["fallbacks"] == "default"
    assert body["max_tokens"] == 16000
    assert "temperature" not in body
    calls = rows(
        sync_engine,
        "SELECT model FROM platform_model_calls WHERE profile = :p",
        p=profile["name"],
    )
    assert [c["model"] for c in calls] == [CLAUDE]


def test_no_key_on_the_worker_fails_the_test_until_it_is_set(
    client: TestClient, admin: dict[str, str], db_url: str
) -> None:
    _drain_stale_tests(db_url)
    profile = _create(client, admin, **_claude())

    assert _test_with_real_gateway(db_url, None) == []

    found = _listed(client, admin, profile["id"])
    assert (found["state"], found["error_code"]) == ("failed", "missing_api_key")

    resp = client.post(f"{URL}/{profile['id']}/test", headers=admin)
    assert resp.status_code == 200, resp.text
    _test_with_real_gateway(db_url, "sk-ant-test")
    assert _listed(client, admin, profile["id"])["state"] == "verified"


def test_a_retired_profile_keeps_serving_what_is_pinned_to_it(
    client: TestClient, admin: dict[str, str], db_url: str, gateway: FakeGateway
) -> None:
    profile = _verified(client, admin, db_url, gateway, num_ctx=24000)
    client.post(f"{URL}/{profile['id']}/retire", headers=admin)

    (body,) = _gateway_call(db_url, profile["name"])

    assert body["options"]["num_ctx"] == 24000


def test_budgets_read_the_stored_context_size(
    client: TestClient, admin: dict[str, str], db_url: str
) -> None:
    profile = _create(client, admin, num_ctx=48000)

    async def scenario() -> int:
        engine = create_engine(Settings(database_url=db_url))
        try:
            return (await registry.chat_profile(engine, profile["name"])).num_ctx
        finally:
            await engine.dispose()

    assert run_async(scenario()) == 48000


def test_an_unknown_name_is_an_unknown_profile(db_url: str) -> None:
    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            await registry.chat_profile(engine, "no-such-profile")
        finally:
            await engine.dispose()

    with pytest.raises(UnknownModelProfileError):
        run_async(scenario())


@pytest.mark.parametrize("name", list(SEEDED))
def test_a_seeded_profile_resolves_to_the_definition_the_code_used_to_hold(
    db_url: str, name: str
) -> None:
    async def scenario() -> tuple[Any, Any]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            resolved = await registry.profile_resolver(engine)(name)
            return resolved, await registry.chat_profile(engine, name)
        finally:
            await engine.dispose()

    resolved, budgeted = run_async(scenario())
    assert resolved == budgeted == SEEDED[name]


# --- the allowlist --------------------------------------------------------------------------


def test_the_allowlist_is_seeded_with_the_seeded_profiles_models(
    client: TestClient, admin: dict[str, str]
) -> None:
    resp = client.get(APPROVED_URL, headers=admin)
    assert resp.status_code == 200, resp.text
    pairs = {(a["provider"], a["model"]) for a in resp.json()["items"]}
    assert {(p.provider, p.model) for p in SEEDED.values()} <= pairs
    assert ("anthropic", CLAUDE_SONNET) in pairs


def test_the_claude_seed_has_the_deterministic_ids(sync_engine: Engine) -> None:
    seeded = rows(
        sync_engine,
        "SELECT id, model FROM registry_approved_models "
        "WHERE provider = 'anthropic' AND created_by IS NULL",
    )
    ids = {row["model"]: UUID(str(row["id"])) for row in seeded}
    for model in (CLAUDE, CLAUDE_SONNET):
        assert ids[model] == uuid5(SEED_NAMESPACE, f"approved-model/anthropic/{model}")


def test_an_added_model_can_be_used_and_removing_it_leaves_profiles_alone(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    model = f"model-{uuid4().hex[:10]}:latest"
    added = client.post(APPROVED_URL, json={"provider": "ollama", "model": model}, headers=admin)
    assert added.status_code == 201, added.text
    entry = added.json()
    profile = _create(client, admin, model=model)

    duplicate = client.post(
        APPROVED_URL, json={"provider": "ollama", "model": model}, headers=admin
    )
    assert duplicate.status_code == 409, duplicate.text
    assert_problem(duplicate.json(), 409, "registry_approved_model_duplicate")

    removed = client.delete(f"{APPROVED_URL}/{entry['id']}", headers=admin)
    assert removed.status_code == 204, removed.text
    assert _listed(client, admin, profile["id"])["model"] == model
    assert client.delete(f"{APPROVED_URL}/{entry['id']}", headers=admin).status_code == 404

    refused = client.post(URL, json=_form(model=model), headers=admin)
    assert refused.status_code == 422, refused.text
    types = [e["event_type"] for e in _events(sync_engine, entry["id"])]
    assert types == ["registry.approved_model.added", "registry.approved_model.removed"]


# --- authorization and grants ---------------------------------------------------------------


def test_a_non_admin_gets_no_data(client: TestClient, admin: dict[str, str]) -> None:
    profile = _create(client, admin)
    headers, _ = _signed_in(client, "Pre Sales", "presales_engineer")
    any_id = profile["id"]

    assert client.get(URL, headers=headers).status_code == 403
    assert client.post(URL, json=_form(), headers=headers).status_code == 403
    assert client.post(f"{URL}/{any_id}/test", headers=headers).status_code == 403
    assert client.post(f"{URL}/{any_id}/retire", headers=headers).status_code == 403
    assert client.get(APPROVED_URL, headers=headers).status_code == 403
    assert (
        client.post(
            APPROVED_URL, json={"provider": "ollama", "model": "x"}, headers=headers
        ).status_code
        == 403
    )
    assert client.delete(f"{APPROVED_URL}/{any_id}", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE registry_model_profiles SET model = 'x' WHERE id = :id",
        "UPDATE registry_model_profiles SET num_ctx = 20000 WHERE id = :id",
        "DELETE FROM registry_model_profiles WHERE id = :id",
    ],
)
def test_the_app_role_cannot_change_a_definition(
    client: TestClient, admin: dict[str, str], sync_engine: Engine, statement: str
) -> None:
    profile = _create(client, admin)
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(sa.text(statement), {"id": profile["id"]})


def test_the_app_role_cannot_update_an_approved_model(sync_engine: Engine) -> None:
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(sa.text("UPDATE registry_approved_models SET model = model"))


def test_the_table_has_no_secret_column(sync_engine: Engine) -> None:
    columns = rows(
        sync_engine,
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t",
        t="registry_model_profiles",
    )
    names = {c["column_name"] for c in columns}
    assert not {n for n in names if "key" in n or "url" in n or "secret" in n}


# --- migration 0062 -------------------------------------------------------------------------


def _insert_profile(conn: sa.Connection, provider_name: str, effort: str | None) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO registry_model_profiles "
            "(id, name, provider, model, num_ctx, temperature, reasoning_effort, state) "
            "VALUES (:id, :name, :provider, 'm', 20000, :temperature, :effort, 'untested')"
        ),
        {
            "id": uuid4(),
            "name": _name(),
            "provider": provider_name,
            "temperature": None if effort else 0.1,
            "effort": effort,
        },
    )


def _insert_approved(conn: sa.Connection, provider_name: str) -> None:
    conn.execute(
        sa.text("INSERT INTO registry_approved_models (id, provider, model) VALUES (:id, :p, :m)"),
        {"id": uuid4(), "p": provider_name, "m": f"m-{uuid4().hex[:10]}"},
    )


def _checks(engine: Engine) -> dict[str, str]:
    found = rows(
        engine,
        "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
        "WHERE contype = 'c' AND conrelid = ANY("
        "ARRAY['registry_model_profiles'::regclass, 'registry_approved_models'::regclass])",
    )
    return {row["conname"]: row["definition"] for row in found}


@pytest.mark.parametrize(
    "insert",
    [
        lambda conn: _insert_profile(conn, "anthropic", "medium"),
        lambda conn: _insert_profile(conn, "anthropic", None),
        lambda conn: _insert_approved(conn, "anthropic"),
    ],
)
def test_the_old_constraints_refuse_anthropic_after_a_downgrade(
    sync_engine: Engine, insert: Any
) -> None:
    _alembic("downgrade", BEFORE_ANTHROPIC)
    try:
        with pytest.raises(sa.exc.IntegrityError), sync_engine.begin() as conn:
            insert(conn)
    finally:
        _alembic("upgrade", "head")


def test_the_downgrade_removes_anthropic_rows_and_the_upgrade_restores_the_seed(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    claude = _create(client, admin, **_claude())
    other = _create(client, admin)
    widened = _checks(sync_engine)
    added = f"claude-{uuid4().hex[:10]}"
    resp = client.post(APPROVED_URL, json={"provider": "anthropic", "model": added}, headers=admin)
    assert resp.status_code == 201, resp.text

    _alembic("downgrade", BEFORE_ANTHROPIC)
    try:
        narrowed = _checks(sync_engine)
        assert set(narrowed) == set(widened)  # replaced by name, none left beside the old ones
        assert not [d for d in narrowed.values() if "anthropic" in d]
        ids = {str(p["id"]) for p in rows(sync_engine, "SELECT id FROM registry_model_profiles")}
        assert claude["id"] not in ids
        assert other["id"] in ids
        approved = rows(sync_engine, "SELECT provider FROM registry_approved_models")
        assert {a["provider"] for a in approved} == {"ollama", "openai"}
    finally:
        _alembic("upgrade", "head")

    assert _checks(sync_engine) == widened
    seeded = rows(
        sync_engine, "SELECT model FROM registry_approved_models WHERE provider = 'anthropic'"
    )
    assert {s["model"] for s in seeded} == {CLAUDE, CLAUDE_SONNET}


# --- migration 0063: the seeded chat profiles --------------------------------------------------


def _seed_id(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"model-profile/{name}")


def _profile_rows(engine: Engine) -> dict[str, dict[str, Any]]:
    found = rows(engine, "SELECT * FROM registry_model_profiles WHERE name = ANY(:n)", n=[*SEEDED])
    return {row["name"]: row for row in found}


def test_the_seeded_profiles_are_listed_as_verified(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    resp = client.get(URL, headers=admin)
    assert resp.status_code == 200, resp.text
    listed = {p["name"]: p for p in resp.json()["items"]}
    for name, profile in SEEDED.items():
        item = listed[name]
        assert item["id"] == str(_seed_id(name))
        assert item["state"] == "verified"
        assert (item["provider"], item["model"], item["num_ctx"]) == (
            profile.provider,
            profile.model,
            profile.num_ctx,
        )
    assert listed["ollama-cloud-chat"]["temperature"] == listed["openai-chat"]["temperature"] == 0.1
    claude = listed["anthropic-opus-chat"]
    assert (claude["temperature"], claude["reasoning_effort"]) == (None, "medium")
    assert all(row["created_by"] is None for row in _profile_rows(sync_engine).values())


def test_a_seeded_profile_can_be_pinned(
    client: TestClient,
    admin: dict[str, str],
    test_manifest: str,  # noqa: F811
) -> None:
    agent = _register(client, admin, test_manifest)
    options = client.get(f"{AGENTS_URL}/{test_manifest}/config-options", headers=admin).json()
    assert set(SEEDED) <= set(options["model_profiles"])

    resp = _new_version(client, admin, agent, "openai-chat")
    assert resp.status_code == 201, resp.text
    assert resp.json()["effective_model"] == {"profile": "openai-chat", "model": "gpt-4.1-mini"}


def test_an_unpinned_seeded_profile_can_be_retired_and_a_pinned_one_cannot(
    client: TestClient, admin: dict[str, str], sync_engine: Engine
) -> None:
    # The seeded Agents pin `ollama-cloud-chat`; no test pins `anthropic-opus-chat`.
    pinned = client.post(f"{URL}/{_seed_id('ollama-cloud-chat')}/retire", headers=admin)
    assert pinned.status_code == 409, pinned.text
    assert_problem(pinned.json(), 409, "registry_model_profile_in_use")

    try:
        retired = client.post(f"{URL}/{_seed_id('anthropic-opus-chat')}/retire", headers=admin)
        assert retired.status_code == 200, retired.text
        assert retired.json()["state"] == "retired"
    finally:
        with sync_engine.begin() as conn:  # the tables are shared: restore the seed
            conn.execute(
                sa.text("UPDATE registry_model_profiles SET state = 'verified' WHERE id = :id"),
                {"id": _seed_id("anthropic-opus-chat")},
            )


def test_the_seed_migration_never_imports_the_app() -> None:
    source = SEED_MIGRATION.read_text(encoding="utf-8")
    assert "from app" not in source and "import app" not in source


def test_the_seed_round_trip_keeps_a_name_that_already_exists(sync_engine: Engine) -> None:
    owner_url = os.environ.get("PSA_MIGRATIONS_DATABASE_URL")
    assert owner_url, "PSA_MIGRATIONS_DATABASE_URL (the owner role) is needed to clean up"
    existing = uuid4()
    _alembic("downgrade", BEFORE_SEED)
    try:
        assert _profile_rows(sync_engine) == {}
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO registry_model_profiles "
                    "(id, name, provider, model, num_ctx, temperature, state) "
                    "VALUES (:id, 'openai-chat', 'openai', 'gpt-4.1-mini', 20000, 0.5, 'failed')"
                ),
                {"id": existing},
            )

        _alembic("upgrade", "head")
        upgraded = _profile_rows(sync_engine)
        assert UUID(str(upgraded["openai-chat"]["id"])) == existing
        assert upgraded["openai-chat"]["state"] == "failed"
        for name in ("ollama-cloud-chat", "anthropic-opus-chat"):
            assert UUID(str(upgraded[name]["id"])) == _seed_id(name)
            assert upgraded[name]["state"] == "verified"

        _alembic("downgrade", BEFORE_SEED)
        downgraded = _profile_rows(sync_engine)
        assert set(downgraded) == {"openai-chat"}
        assert UUID(str(downgraded["openai-chat"]["id"])) == existing
    finally:
        owner = sa.create_engine(owner_url)
        try:
            with owner.begin() as conn:  # psa_app may not delete a profile
                conn.execute(
                    sa.text("DELETE FROM registry_model_profiles WHERE id = :id"), {"id": existing}
                )
        finally:
            owner.dispose()
        _alembic("upgrade", "head")

    restored = _profile_rows(sync_engine)
    assert {name: UUID(str(row["id"])) for name, row in restored.items()} == {
        name: _seed_id(name) for name in SEEDED
    }
