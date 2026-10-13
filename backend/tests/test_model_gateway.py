"""The ModelGateway (AD-8, Story 2.4): adapter, retries, errors, semaphore and call rows.

Both providers (Ollama's `/api/chat` and the OpenAI-compatible `/v1/chat/completions`) are
stubbed with one `httpx.MockTransport`; no live model is needed. Contract tests take the
`provider` fixture and run once per adapter. Call rows are
asserted in Postgres (as `psa_app`), looked up by the `call_id` the gateway returns.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from pydantic import BaseModel, ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.model_gateway.gateway import ModelGateway, field_paths
from app.platform.model_gateway.openai_compat import schema_name
from app.platform.model_gateway.port import (
    CallerMetadata,
    Message,
    ModelGatewayError,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredRequest,
    StructuredResult,
)
from app.platform.model_gateway.profiles import (
    MODEL_PROFILES,
    UnknownModelProfileError,
    get_profile,
)
from app.platform.model_gateway.semaphore import PrioritySemaphore
from tests.conftest import UNREACHABLE_DB, run_async

# Sentinels standing in for customer content: they must never reach logs, rows or errors.
PROMPT_SECRET = "PROMPT-SECRET-Acme-warehouse-7f3a"
REPLY_SECRET = "REPLY-SECRET-conveyor-91bc"
DIGEST = "sha256:0123456789abcdef"
RUN_ID = UUID("01920000-0000-7000-8000-000000000001")
OPPORTUNITY_ID = UUID("01920000-0000-7000-8000-000000000002")


class Requirement(BaseModel):
    title: str
    priority: int


class Extraction(BaseModel):
    requirements: list[Requirement]
    summary: str


VALID = json.dumps(
    {"requirements": [{"title": REPLY_SECRET, "priority": 1}], "summary": REPLY_SECRET}
)
# Wrong type at requirements.0.priority and a missing `summary`; the bad value is content.
INVALID = json.dumps({"requirements": [{"title": "x", "priority": REPLY_SECRET}]})


# The chat endpoint of each provider (the OpenAI base URL is `http://ollama.test/v1`).
CHAT_PATHS = {"/api/chat": "ollama", "/v1/chat/completions": "openai"}
# The profile each contract test uses per provider; both serve `LOCAL_MODEL`.
PROFILES = {"ollama": "local-chat", "openai": "local-chat-openai"}
LOCAL_MODEL = "qwen3:8b"
OPENAI_URL = "http://ollama.test/v1/chat/completions"
API_KEY = "sk-SECRET-key-5d2e"


@dataclass(frozen=True)
class Reply:
    """A scripted model reply, rendered in the envelope of whichever provider was asked."""

    content: str
    prompt_tokens: int = 11
    eval_tokens: int = 7
    done_reason: str = "stop"

    def response(self, provider: str) -> httpx.Response:
        if provider == "ollama":
            return httpx.Response(
                200,
                json={
                    "model": "stub",
                    "message": {"role": "assistant", "content": self.content},
                    "done": True,
                    "done_reason": self.done_reason,
                    "prompt_eval_count": self.prompt_tokens,
                    "eval_count": self.eval_tokens,
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "model": "stub",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": self.content},
                        "finish_reason": self.done_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.eval_tokens,
                    "total_tokens": self.prompt_tokens + self.eval_tokens,
                },
            },
        )


def _chat_reply(
    content: str, prompt_tokens: int = 11, eval_tokens: int = 7, done_reason: str = "stop"
) -> Reply:
    return Reply(content, prompt_tokens, eval_tokens, done_reason)


def _tags(model: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": model, "model": model, "digest": DIGEST}]})


ScriptItem = Callable[[], Awaitable[httpx.Response | Reply]] | httpx.Response | Reply | str


class StubOllama:
    """Answers both chat endpoints (`/api/chat`, `/v1/chat/completions`) from one script of
    replies, in the envelope of the endpoint asked, and `/api/tags` with a fixed digest."""

    def __init__(
        self,
        replies: list[ScriptItem],
        tags_model: str | None = None,
        tags_error: Exception | None = None,
    ) -> None:
        self.replies = list(replies)
        self.tags_error = tags_error
        self.chat_bodies: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self.tags_calls = 0
        self.tags_model = tags_model

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/tags":
            self.tags_calls += 1
            if self.tags_error is not None:
                raise self.tags_error
            if self.tags_model is None:
                return httpx.Response(200, json={"models": []})
            return _tags(self.tags_model)
        provider = CHAT_PATHS[request.url.path]
        self.chat_bodies.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if not isinstance(reply, str | httpx.Response | Reply):
            reply = await reply()
        if isinstance(reply, str):
            reply = Reply(reply)
        if isinstance(reply, Reply):
            return reply.response(provider)
        return reply


@pytest.fixture(params=["ollama", "openai"])
def provider(request: pytest.FixtureRequest) -> str:
    """Runs a contract test once per provider (through `local-chat` / `local-chat-openai`)."""
    name: str = request.param
    return name


def _digest(provider: str) -> str:
    """The digest a call records when the stub's `/api/tags` lists `LOCAL_MODEL`."""
    return DIGEST if provider == "ollama" else "unknown"


def _settings(db_url: str, provider: str | None = None, **overrides: Any) -> Settings:
    fields: dict[str, Any] = {
        "database_url": db_url,
        "ollama_url": "http://ollama.test",
        "openai_base_url": "http://ollama.test/v1",
        "model_max_retries": 2,
        # One slot, so the slot tests can hold it (the default is 3 since Epic 5 slice 5A).
        "model_slots": 1,
    }
    if provider is not None:
        fields["model_profile_chat"] = PROFILES[provider]
    return Settings(**(fields | overrides))


def _request(**overrides: Any) -> StructuredRequest[Extraction]:
    fields: dict[str, Any] = {
        "messages": [
            Message(role="system", content="Extract requirements."),
            Message(role="user", content=f"<data>{PROMPT_SECRET}</data>"),
        ],
        "output_model": Extraction,
        "caller": CallerMetadata(
            agent_id="intake_agent",
            config_version="0.1.0+p1",
            run_id=RUN_ID,
            opportunity_id=OPPORTUNITY_ID,
        ),
        "priority": "interactive",
        "timeout_s": 5,
    }
    fields.update(overrides)
    return StructuredRequest(**fields)


def _call(
    db_url: str,
    stub: StubOllama,
    request: StructuredRequest[Extraction] | None = None,
    provider: str | None = None,
    **settings: Any,
) -> StructuredResult[Extraction] | ModelGatewayError:
    """Run one call; return the result, or the typed error it raised. `provider` picks that
    provider's local profile; None keeps the default profile (`demo-chat`, Ollama)."""

    async def scenario() -> StructuredResult[Extraction] | ModelGatewayError:
        config = _settings(db_url, provider, **settings)
        engine = create_engine(config)
        try:
            async with ModelGateway(config, engine, transport=httpx.MockTransport(stub)) as gateway:
                try:
                    return await gateway.complete_structured(request or _request())
                except ModelGatewayError as exc:
                    return exc
        finally:
            await engine.dispose()

    return run_async(scenario())


def _row(engine: Engine, call_id: UUID | None) -> dict[str, Any]:
    assert call_id is not None
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT * FROM platform_model_calls WHERE id = :id"), {"id": call_id}
        ).one()
    return dict(row._mapping)


async def _until(condition: Callable[[], bool], timeout_s: float = 5) -> None:
    """Yield to the loop until `condition()` holds (no fixed sleeps)."""
    async with asyncio.timeout(timeout_s):
        # The semaphore exposes counts, not events; yielding once per loop pass is enough.
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0)


def _count_rows(engine: Engine, config_version: str) -> int:
    with engine.connect() as conn:
        count: int = conn.execute(
            sa.text("SELECT count(*) FROM platform_model_calls WHERE config_version = :v"),
            {"v": config_version},
        ).scalar_one()
    return count


def _assert_private(*texts: str) -> None:
    for text in texts:
        assert PROMPT_SECRET not in text
        assert REPLY_SECRET not in text


# --- valid call and request shape --------------------------------------------------------


def test_valid_reply_returns_result_and_writes_one_ok_row(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    stub = StubOllama([VALID], tags_model=LOCAL_MODEL)
    result = _call(db_url, stub, provider=provider)
    assert isinstance(result, StructuredResult)
    assert result.value.requirements[0].priority == 1
    assert (result.input_tokens, result.output_tokens, result.attempts) == (11, 7, 1)
    assert result.model_digest == _digest(provider)
    assert (result.profile, result.model) == (PROFILES[provider], LOCAL_MODEL)
    row = _row(sync_engine, result.call_id)
    assert row["outcome"] == "ok"
    assert row["attempts"] == 1
    assert row["error_code"] is None
    assert (row["input_tokens"], row["output_tokens"]) == (11, 7)
    assert row["latency_ms"] == result.latency_ms >= 0
    assert row["model_digest"] == _digest(provider)
    assert (row["agent_id"], row["config_version"]) == ("intake_agent", "0.1.0+p1")
    assert (row["run_id"], row["opportunity_id"], row["task_id"]) == (RUN_ID, OPPORTUNITY_ID, None)
    assert (row["profile"], row["model"], row["priority"]) == (
        PROFILES[provider],
        LOCAL_MODEL,
        "interactive",
    )
    assert result.call_id.version == 7


def test_request_body_has_schema_format_no_stream_and_profile_options(db_url: str) -> None:
    stub = StubOllama([VALID])
    _call(db_url, stub)
    [body] = stub.chat_bodies
    assert body["format"] == Extraction.model_json_schema()
    assert body["stream"] is False
    assert body["model"] == "gpt-oss:120b-cloud"
    assert body["options"] == {"temperature": 0.1, "num_ctx": 32768}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_unknown_digest_is_recorded_not_an_error(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([VALID], tags_model=None)  # /api/tags doesn't list the model
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    assert result.model_digest == "unknown"
    assert _row(sync_engine, result.call_id)["model_digest"] == "unknown"


def test_digest_is_cached_per_gateway(db_url: str) -> None:
    stub = StubOllama([VALID, VALID], tags_model="gpt-oss:120b-cloud")

    async def scenario() -> None:
        settings = _settings(db_url)
        engine = create_engine(settings)
        try:
            async with ModelGateway(
                settings, engine, transport=httpx.MockTransport(stub)
            ) as gateway:
                await gateway.complete_structured(_request())
                await gateway.complete_structured(_request())
        finally:
            await engine.dispose()

    run_async(scenario())
    assert stub.tags_calls == 1


# --- retries ------------------------------------------------------------------------------


def test_invalid_then_valid_retries_with_field_paths_only(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    stub = StubOllama([INVALID, VALID])
    result = _call(db_url, stub, provider=provider)
    assert isinstance(result, StructuredResult)
    assert result.attempts == 2
    assert (result.input_tokens, result.output_tokens) == (22, 14)
    first, second = stub.chat_bodies
    assert first["messages"] == second["messages"][:-2]
    # The invalid reply goes back as the assistant turn, then the correction.
    assert second["messages"][-2] == {"role": "assistant", "content": INVALID}
    correction = second["messages"][-1]
    assert correction["role"] == "user"
    assert "requirements.0.priority" in correction["content"]
    assert "summary" in correction["content"]
    _assert_private(correction["content"])
    row = _row(sync_engine, result.call_id)
    assert (row["outcome"], row["attempts"]) == ("ok", 2)


def test_non_json_reply_is_retried_as_root_error(db_url: str, provider: str) -> None:
    stub = StubOllama([f"not json {REPLY_SECRET}", VALID])
    result = _call(db_url, stub, provider=provider)
    assert isinstance(result, StructuredResult)
    correction = stub.chat_bodies[1]["messages"][-1]["content"]
    assert "not a valid JSON object" in correction
    _assert_private(correction)


def test_retries_exhausted_raise_invalid_output_after_recording(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    stub = StubOllama([INVALID, INVALID, INVALID])
    error = _call(db_url, stub, provider=provider)
    assert isinstance(error, ModelOutputInvalidError)
    assert len(stub.chat_bodies) == 3
    assert "requirements.0.priority" in error.field_paths
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["attempts"], row["error_code"]) == (
        "invalid_output",
        3,
        "invalid_output",
    )
    assert row["output_tokens"] == 21


def test_third_attempt_carries_only_the_latest_reply_and_correction(
    db_url: str, provider: str
) -> None:
    stub = StubOllama([INVALID, "[]", VALID])
    result = _call(db_url, stub, provider=provider)
    assert isinstance(result, StructuredResult)
    third = stub.chat_bodies[2]["messages"]
    assert len(third) == 4
    assert third[-2] == {"role": "assistant", "content": "[]"}


def test_truncated_reply_fails_at_once_without_retry(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    stub = StubOllama([_chat_reply('{"requirements": [', done_reason="length"), VALID])
    error = _call(db_url, stub, provider=provider)
    assert isinstance(error, ModelOutputInvalidError)
    assert error.error_code == "truncated"
    assert len(stub.chat_bodies) == 1
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == (
        "invalid_output",
        "truncated",
        1,
    )
    assert row["output_tokens"] == 7


def test_field_paths_mask_non_identifier_keys_and_cap_at_20() -> None:
    class Counts(BaseModel):
        counts: dict[str, int]

    with pytest.raises(ValidationError) as info:
        Counts.model_validate({"counts": {f"key with {REPLY_SECRET}": "x", "ok_key": "y"}})
    assert field_paths(info.value) == ["counts.<key>", "counts.ok_key"]

    class Many(BaseModel):
        values: list[int]

    with pytest.raises(ValidationError) as info:
        Many.model_validate({"values": ["x"] * 30})
    paths = field_paths(info.value)
    assert len(paths) == 20
    assert paths[0] == "values.0"


def test_max_retries_zero_means_one_attempt(db_url: str, provider: str) -> None:
    stub = StubOllama([INVALID])
    error = _call(db_url, stub, provider=provider, model_max_retries=0)
    assert isinstance(error, ModelOutputInvalidError)
    assert len(stub.chat_bodies) == 1


# --- errors -------------------------------------------------------------------------------


def test_connection_refused_raises_unavailable(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    async def refuse() -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    error = _call(db_url, StubOllama([refuse]), provider=provider)
    assert isinstance(error, ModelUnavailableError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("error", "connection", 1)
    assert row["model_digest"] == "unknown"


def test_digest_lookup_failure_still_records_unknown(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([httpx.Response(502)], tags_error=httpx.ConnectError("refused"))
    error = _call(db_url, stub)
    assert isinstance(error, ModelUnavailableError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["model_digest"]) == (
        "error",
        "http_502",
        "unknown",
    )


def test_unknown_digest_is_cached_briefly(db_url: str) -> None:
    stub = StubOllama([VALID, VALID], tags_model=None)

    async def scenario() -> None:
        settings = _settings(db_url)
        engine = create_engine(settings)
        try:
            async with ModelGateway(settings, engine, transport=httpx.MockTransport(stub)) as gw:
                await gw.complete_structured(_request())
                await gw.complete_structured(_request())
        finally:
            await engine.dispose()

    run_async(scenario())
    assert stub.tags_calls == 1


@pytest.mark.parametrize(
    "envelope",
    [{"done": True}, {"choices": []}, [1, 2], "not json"],
    ids=["no_content", "no_choices", "list", "not_json"],
)
def test_reply_without_message_content_is_bad_envelope(
    db_url: str, sync_engine: Engine, provider: str, envelope: Any
) -> None:
    response = (
        httpx.Response(200, text=envelope)
        if isinstance(envelope, str)
        else httpx.Response(200, json=envelope)
    )
    stub = StubOllama([response, VALID])
    error = _call(db_url, stub, provider=provider)
    assert isinstance(error, ModelUnavailableError)
    assert len(stub.chat_bodies) == 1
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("error", "bad_envelope", 1)


@pytest.mark.parametrize(
    ("exc", "error_type", "outcome", "code"),
    [
        (httpx.ReadTimeout("slow"), ModelTimeoutError, "timeout", "timeout"),
        (httpx.ConnectTimeout("slow"), ModelUnavailableError, "error", "connect_timeout"),
        (httpx.TooManyRedirects("loop"), ModelUnavailableError, "error", "transport"),
        (httpx.DecodingError("gzip"), ModelUnavailableError, "error", "transport"),
    ],
    ids=["read_timeout", "connect_timeout", "too_many_redirects", "decoding"],
)
def test_httpx_errors_map_to_typed_errors(
    db_url: str,
    sync_engine: Engine,
    provider: str,
    exc: httpx.HTTPError,
    error_type: type[ModelGatewayError],
    outcome: str,
    code: str,
) -> None:
    async def fail() -> httpx.Response:
        raise exc

    error = _call(db_url, StubOllama([fail]), provider=provider)
    assert type(error) is error_type
    assert isinstance(error, ModelGatewayError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"]) == (outcome, code)


def test_server_error_raises_unavailable_without_retry(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    stub = StubOllama([httpx.Response(503, text=f"overloaded {PROMPT_SECRET}")])
    error = _call(db_url, stub, provider=provider)
    assert isinstance(error, ModelUnavailableError)
    assert len(stub.chat_bodies) == 1
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"]) == ("error", "http_503")
    _assert_private(str(error))


def test_redirect_is_unavailable_not_bad_envelope(
    db_url: str, sync_engine: Engine, provider: str
) -> None:
    stub = StubOllama([httpx.Response(307, headers={"Location": "http://elsewhere.test/"})])
    error = _call(db_url, stub, provider=provider)
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "http_307"
    assert len(stub.chat_bodies) == 1
    assert _row(sync_engine, error.call_id)["error_code"] == "http_307"


def test_slow_reply_raises_timeout(db_url: str, sync_engine: Engine, provider: str) -> None:
    async def never() -> httpx.Response:
        await asyncio.Event().wait()  # never answers
        raise AssertionError("unreachable")

    error = _call(db_url, StubOllama([never]), _request(timeout_s=0.2), provider=provider)
    assert isinstance(error, ModelTimeoutError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("timeout", "timeout", 1)


def test_cancelled_call_writes_no_row(db_url: str, sync_engine: Engine, provider: str) -> None:
    marker = f"cancelled-{new_id()}"

    async def scenario() -> None:
        settings = _settings(db_url, provider)
        engine = create_engine(settings)
        started = asyncio.Event()

        async def hang() -> httpx.Response:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        caller = CallerMetadata(agent_id="intake_agent", config_version=marker)
        try:
            async with ModelGateway(
                settings, engine, transport=httpx.MockTransport(StubOllama([hang]))
            ) as gateway:
                task = asyncio.create_task(gateway.complete_structured(_request(caller=caller)))
                await started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert gateway.semaphore.free == 1
        finally:
            await engine.dispose()

    run_async(scenario())
    assert _count_rows(sync_engine, marker) == 0


@pytest.mark.parametrize("ok", [True, False], ids=["ok", "error"])
def test_failed_record_write_does_not_replace_the_outcome(
    caplog: pytest.LogCaptureFixture, ok: bool, provider: str
) -> None:
    caplog.set_level(logging.ERROR)
    replies: list[Any] = [VALID] if ok else [httpx.Response(503)]
    outcome = _call(UNREACHABLE_DB, StubOllama(replies), provider=provider, db_connect_timeout_s=1)
    if ok:
        assert isinstance(outcome, StructuredResult)
        assert outcome.value.summary == REPLY_SECRET
    else:
        assert isinstance(outcome, ModelUnavailableError)
        assert outcome.error_code == "http_503"
    [record] = [r for r in caplog.records if r.getMessage() == "model_call.record_failed"]
    assert record.__dict__["call_id"] == str(outcome.call_id)
    assert record.__dict__["exc_type"]
    _assert_private(json.dumps(record.__dict__, default=str))


# --- privacy ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "replies",
    [[VALID], [INVALID, INVALID, INVALID], [httpx.Response(500, text=REPLY_SECRET)]],
    ids=["ok", "invalid_output", "error"],
)
def test_no_prompt_or_reply_text_in_logs_rows_or_errors(
    db_url: str,
    sync_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    provider: str,
    replies: list[Any],
) -> None:
    caplog.set_level(logging.DEBUG)
    outcome = _call(db_url, StubOllama(replies), provider=provider)
    call_id = outcome.call_id
    row = _row(sync_engine, call_id)
    _assert_private(json.dumps(row, default=str))
    _assert_private(repr(outcome))
    if isinstance(outcome, ModelGatewayError):
        _assert_private(str(outcome), repr(outcome.__cause__), repr(outcome.__context__))
    records = [r for r in caplog.records if r.name.startswith("app.")]
    assert any(r.getMessage().startswith("model_call.") for r in records)
    for record in caplog.records:
        _assert_private(record.getMessage(), json.dumps(record.__dict__, default=str))
    _assert_private(repr(_request()))


# --- profiles -----------------------------------------------------------------------------


def test_profiles_are_defined() -> None:
    assert MODEL_PROFILES["demo-chat"].model == "gpt-oss:120b-cloud"
    assert MODEL_PROFILES["demo-chat"].num_ctx == 32768
    assert MODEL_PROFILES["local-chat"].model == "qwen3:8b"
    assert MODEL_PROFILES["local-chat"].num_ctx == 16384
    openai_profile = MODEL_PROFILES["local-chat-openai"]
    assert (openai_profile.model, openai_profile.num_ctx) == ("qwen3:8b", 16384)
    assert openai_profile.provider == "openai"
    cloud = MODEL_PROFILES["openai-chat"]
    assert (cloud.model, cloud.provider) == ("gpt-4.1-mini", "openai")
    assert MODEL_PROFILES["demo-chat"].provider == MODEL_PROFILES["local-chat"].provider == "ollama"
    assert all(p.temperature == 0.1 for p in MODEL_PROFILES.values())
    with pytest.raises(UnknownModelProfileError):
        get_profile("nope")


def test_configured_local_profile_selects_qwen(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([VALID])
    result = _call(db_url, stub, model_profile_chat="local-chat")
    assert isinstance(result, StructuredResult)
    [body] = stub.chat_bodies
    assert body["model"] == "qwen3:8b"
    assert body["options"] == {"temperature": 0.1, "num_ctx": 16384}
    assert _row(sync_engine, result.call_id)["profile"] == "local-chat"


def test_unknown_configured_profile_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PSA_MODEL_PROFILE_CHAT", "gpt-5-turbo")
    with pytest.raises(ValidationError, match="not a known profile"):
        Settings()


def test_request_profile_overrides_configured_one(db_url: str) -> None:
    stub = StubOllama([VALID])
    _call(db_url, stub, _request(profile="local-chat"))
    assert stub.chat_bodies[0]["model"] == "qwen3:8b"


# --- OpenAI-compatible adapter only -------------------------------------------------------


def test_openai_profile_routes_to_the_openai_base_url(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([VALID])
    result = _call(db_url, stub, model_profile_chat="local-chat-openai")
    assert isinstance(result, StructuredResult)
    [request] = stub.requests
    assert (request.method, str(request.url)) == ("POST", OPENAI_URL)
    assert stub.chat_bodies[0]["model"] == "qwen3:8b"
    assert _row(sync_engine, result.call_id)["profile"] == "local-chat-openai"


def test_openai_cloud_profile_sends_the_openai_model_id(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([VALID])
    result = _call(db_url, stub, model_profile_chat="openai-chat")
    assert isinstance(result, StructuredResult)
    [request] = stub.requests
    assert (request.method, str(request.url)) == ("POST", OPENAI_URL)
    assert stub.chat_bodies[0]["model"] == "gpt-4.1-mini"
    assert _row(sync_engine, result.call_id)["profile"] == "openai-chat"


def test_openai_request_body_has_response_format_and_no_context_options(db_url: str) -> None:
    stub = StubOllama([VALID])
    _call(db_url, stub, provider="openai")
    [body] = stub.chat_bodies
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Extraction", "schema": Extraction.model_json_schema()},
    }
    assert body["stream"] is False
    assert body["temperature"] == 0.1
    assert body["model"] == "qwen3:8b"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    for key in ("options", "num_ctx", "format"):
        assert key not in body


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Extraction", "Extraction"),
        ("Gap list: v2 (draft)", "Gap_list__v2__draft_"),
        ("x" * 100, "x" * 64),
        ("", "output"),
        (None, "output"),
    ],
)
def test_openai_schema_name_is_sanitised(title: str | None, name: str) -> None:
    schema: dict[str, Any] = {"type": "object"}
    if title is not None:
        schema["title"] = title
    assert schema_name(schema) == name


def test_openai_digest_is_unknown_without_a_request(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([VALID], tags_model="qwen3:8b")  # /api/tags would know the digest
    result = _call(db_url, stub, provider="openai")
    assert isinstance(result, StructuredResult)
    assert result.model_digest == "unknown"
    assert _row(sync_engine, result.call_id)["model_digest"] == "unknown"
    assert [r.url.path for r in stub.requests] == ["/v1/chat/completions"]
    assert stub.tags_calls == 0


def test_openai_api_key_is_sent_as_bearer_and_never_logged(
    db_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    stub = StubOllama([VALID, httpx.Response(401, text="bad key"), VALID])

    async def scenario() -> ModelGatewayError:
        settings = _settings(db_url, "openai", openai_api_key=f" {API_KEY}\n")
        assert API_KEY not in repr(settings)
        engine = create_engine(settings)
        try:
            async with ModelGateway(settings, engine, transport=httpx.MockTransport(stub)) as gw:
                await gw.complete_structured(_request())
                with pytest.raises(ModelUnavailableError) as info:
                    await gw.complete_structured(_request())
                await gw.complete_structured(_request(profile="local-chat"))  # Ollama: no key
                return info.value
        finally:
            await engine.dispose()

    error = run_async(scenario())
    assert error.error_code == "http_401"
    first, second, ollama_chat, ollama_tags = stub.requests
    assert first.headers["Authorization"] == f"Bearer {API_KEY}"
    assert second.headers["Authorization"] == f"Bearer {API_KEY}"
    assert (ollama_chat.url.path, ollama_tags.url.path) == ("/api/chat", "/api/tags")
    assert "Authorization" not in ollama_chat.headers
    assert "Authorization" not in ollama_tags.headers
    for text in (str(error), repr(error), repr(error.__cause__), repr(error.__context__)):
        assert API_KEY not in text
    for record in caplog.records:
        assert API_KEY not in record.getMessage()
        assert API_KEY not in json.dumps(record.__dict__, default=str)


@pytest.mark.parametrize("key", [None, "", "  \t"], ids=["unset", "empty", "whitespace"])
def test_openai_without_api_key_sends_no_auth_header(db_url: str, key: str | None) -> None:
    stub = StubOllama([VALID])
    _call(db_url, stub, provider="openai", openai_api_key=key)
    [request] = stub.requests
    assert "Authorization" not in request.headers


def test_openai_refusal_is_bad_envelope(db_url: str, sync_engine: Engine) -> None:
    refusal = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": None, "refusal": REPLY_SECRET},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    )
    stub = StubOllama([refusal, VALID])
    error = _call(db_url, stub, provider="openai")
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "bad_envelope"
    assert len(stub.chat_bodies) == 1
    _assert_private(str(error), repr(error))
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("error", "bad_envelope", 1)


@pytest.mark.parametrize(
    "usage",
    [None, "nope", {}, {"prompt_tokens": "11", "completion_tokens": -1}],
    ids=["missing", "not_object", "empty", "bad_values"],
)
def test_openai_missing_or_bad_usage_counts_as_zero(db_url: str, usage: Any) -> None:
    envelope: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": VALID}, "finish_reason": "stop"}]
    }
    if usage is not None:
        envelope["usage"] = usage
    result = _call(db_url, StubOllama([httpx.Response(200, json=envelope)]), provider="openai")
    assert isinstance(result, StructuredResult)
    assert (result.input_tokens, result.output_tokens) == (0, 0)


# --- semaphore (no DB) --------------------------------------------------------------------


def _run_loop[T](coro: Awaitable[T]) -> T:
    async def wrapped() -> T:
        return await coro

    return asyncio.run(wrapped())


def test_interactive_waiter_is_granted_before_earlier_background_waiter() -> None:
    async def scenario() -> list[str]:
        sem = PrioritySemaphore(1)
        order: list[str] = []
        await sem.acquire("background")  # the held slot

        async def waiter(name: str, priority: Any) -> None:
            async with sem.slot(priority):
                order.append(name)

        bg1 = asyncio.create_task(waiter("bg1", "background"))
        await asyncio.sleep(0)
        bg2 = asyncio.create_task(waiter("bg2", "background"))
        await asyncio.sleep(0)
        ia1 = asyncio.create_task(waiter("ia1", "interactive"))
        await asyncio.sleep(0)
        ia2 = asyncio.create_task(waiter("ia2", "interactive"))
        await asyncio.sleep(0)
        assert sem.waiting("background") == 2
        assert sem.waiting("interactive") == 2
        sem.release()
        await asyncio.gather(bg1, bg2, ia1, ia2)
        assert sem.free == 1
        return order

    assert _run_loop(scenario()) == ["ia1", "ia2", "bg1", "bg2"]


def test_cancelled_waiter_does_not_leak_the_slot() -> None:
    async def scenario() -> None:
        sem = PrioritySemaphore(1)
        await sem.acquire("interactive")
        cancelled = asyncio.create_task(sem.acquire("interactive"))
        await asyncio.sleep(0)
        nxt = asyncio.create_task(sem.acquire("background"))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        sem.release()
        await asyncio.wait_for(nxt, timeout=1)  # the next waiter proceeds
        sem.release()
        assert sem.free == 1
        assert sem.waiting() == 0

    _run_loop(scenario())


def test_waiter_cancelled_after_grant_passes_the_slot_on() -> None:
    async def scenario() -> None:
        sem = PrioritySemaphore(1)
        await sem.acquire("interactive")
        granted = asyncio.create_task(sem.acquire("interactive"))
        await asyncio.sleep(0)
        nxt = asyncio.create_task(sem.acquire("background"))
        await asyncio.sleep(0)
        sem.release()  # grants `granted` its slot...
        granted.cancel()  # ...but it is cancelled before it resumes
        with pytest.raises(asyncio.CancelledError):
            await granted
        await asyncio.wait_for(nxt, timeout=1)
        sem.release()
        assert sem.free == 1

    _run_loop(scenario())


def test_over_release_raises() -> None:
    sem = PrioritySemaphore(1)
    with pytest.raises(RuntimeError, match="released more times"):
        sem.release()


def test_slot_is_released_on_error() -> None:
    async def scenario() -> None:
        sem = PrioritySemaphore(2)
        with pytest.raises(RuntimeError):
            async with sem.slot("background"):
                raise RuntimeError("boom")
        assert sem.free == 2

    _run_loop(scenario())


def test_gateway_releases_slot_after_errors_and_cancellation(db_url: str, provider: str) -> None:
    async def scenario() -> None:
        settings = _settings(db_url, provider)
        engine: AsyncEngine = create_engine(settings)
        started = asyncio.Event()

        async def slow() -> Reply:
            started.set()
            await asyncio.sleep(10)
            return _chat_reply(VALID)

        stub = StubOllama([httpx.Response(500), slow, VALID])
        try:
            async with ModelGateway(
                settings, engine, transport=httpx.MockTransport(stub)
            ) as gateway:
                with pytest.raises(ModelUnavailableError):
                    await gateway.complete_structured(_request())
                assert gateway.semaphore.free == 1
                task = asyncio.create_task(gateway.complete_structured(_request()))
                await started.wait()
                assert gateway.semaphore.free == 0
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert gateway.semaphore.free == 1
                result = await gateway.complete_structured(_request(priority="background"))
                assert result.attempts == 1
        finally:
            await engine.dispose()

    run_async(scenario())


def test_gateway_waits_for_a_slot_with_priority(db_url: str, provider: str) -> None:
    """One slot held by a call; a background call queues, then an interactive one: the
    interactive call reaches the model first."""

    async def scenario() -> list[str]:
        settings = _settings(db_url, provider)
        engine = create_engine(settings)
        release_first = asyncio.Event()
        first_started = asyncio.Event()
        seen: list[str] = []

        async def first() -> Reply:
            first_started.set()
            await release_first.wait()
            return _chat_reply(VALID)

        class Recording(StubOllama):
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                if request.url.path in CHAT_PATHS:
                    seen.append(json.loads(request.content)["messages"][-1]["content"])
                return await super().__call__(request)

        stub = Recording([first, VALID, VALID])
        try:
            async with ModelGateway(
                settings, engine, transport=httpx.MockTransport(stub)
            ) as gateway:
                holder = asyncio.create_task(gateway.complete_structured(_request()))
                await first_started.wait()

                def req(tag: str, priority: str) -> StructuredRequest[Extraction]:
                    return _request(messages=[Message(role="user", content=tag)], priority=priority)

                sem = gateway.semaphore
                bg = asyncio.create_task(gateway.complete_structured(req("bg", "background")))
                await _until(lambda: sem.waiting("background") == 1)
                ia = asyncio.create_task(gateway.complete_structured(req("ia", "interactive")))
                await _until(lambda: sem.waiting("interactive") == 1)
                release_first.set()
                await asyncio.gather(holder, bg, ia)
        finally:
            await engine.dispose()
        return seen[1:]

    assert run_async(scenario()) == ["ia", "bg"]


def test_request_validation() -> None:
    caller = CallerMetadata(agent_id="a", config_version="1")
    with pytest.raises(ValueError, match="at least one message"):
        StructuredRequest(messages=[], output_model=Extraction, caller=caller)
    with pytest.raises(ValueError, match="timeout_s"):
        StructuredRequest(
            messages=[Message(role="user", content="x")],
            output_model=Extraction,
            caller=caller,
            timeout_s=0,
        )


def test_app_role_can_only_select_and_insert_call_rows(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        privileges = {
            name
            for name in ("SELECT", "INSERT", "UPDATE", "DELETE")
            if conn.execute(
                sa.text("SELECT has_table_privilege('platform_model_calls', :p)"), {"p": name}
            ).scalar_one()
        }
    assert privileges == {"SELECT", "INSERT"}
