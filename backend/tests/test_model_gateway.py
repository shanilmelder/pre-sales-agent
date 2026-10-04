"""The ModelGateway (AD-8, Story 2.4): adapter, retries, errors, semaphore and call rows.

Ollama is stubbed with `httpx.MockTransport`; no live model is needed. Call rows are
asserted in Postgres (as `psa_app`), looked up by the `call_id` the gateway returns.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
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


def _chat_reply(
    content: str, prompt_tokens: int = 11, eval_tokens: int = 7, done_reason: str = "stop"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "stub",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": prompt_tokens,
            "eval_count": eval_tokens,
        },
    )


def _tags(model: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": model, "model": model, "digest": DIGEST}]})


class StubOllama:
    """Answers `/api/chat` from a script of replies and `/api/tags` with a fixed digest."""

    def __init__(
        self,
        replies: list[Callable[[], Awaitable[httpx.Response]] | httpx.Response | str],
        tags_model: str | None = None,
        tags_error: Exception | None = None,
    ) -> None:
        self.replies = list(replies)
        self.tags_error = tags_error
        self.chat_bodies: list[dict[str, Any]] = []
        self.tags_calls = 0
        self.tags_model = tags_model

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            self.tags_calls += 1
            if self.tags_error is not None:
                raise self.tags_error
            if self.tags_model is None:
                return httpx.Response(200, json={"models": []})
            return _tags(self.tags_model)
        assert request.url.path == "/api/chat"
        self.chat_bodies.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, str):
            return _chat_reply(reply)
        if isinstance(reply, httpx.Response):
            return reply
        return await reply()


def _settings(db_url: str, **overrides: Any) -> Settings:
    fields: dict[str, Any] = {
        "database_url": db_url,
        "ollama_url": "http://ollama.test",
        "model_max_retries": 2,
    }
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
    **settings: Any,
) -> StructuredResult[Extraction] | ModelGatewayError:
    """Run one call; return the result, or the typed error it raised."""

    async def scenario() -> StructuredResult[Extraction] | ModelGatewayError:
        config = _settings(db_url, **settings)
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


def test_valid_reply_returns_result_and_writes_one_ok_row(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([VALID], tags_model="gpt-oss:120b-cloud")
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    assert result.value.requirements[0].priority == 1
    assert (result.input_tokens, result.output_tokens, result.attempts) == (11, 7, 1)
    assert result.model_digest == DIGEST
    assert (result.profile, result.model) == ("demo-chat", "gpt-oss:120b-cloud")
    row = _row(sync_engine, result.call_id)
    assert row["outcome"] == "ok"
    assert row["attempts"] == 1
    assert row["error_code"] is None
    assert (row["input_tokens"], row["output_tokens"]) == (11, 7)
    assert row["latency_ms"] == result.latency_ms >= 0
    assert row["model_digest"] == DIGEST
    assert (row["agent_id"], row["config_version"]) == ("intake_agent", "0.1.0+p1")
    assert (row["run_id"], row["opportunity_id"], row["task_id"]) == (RUN_ID, OPPORTUNITY_ID, None)
    assert (row["profile"], row["model"], row["priority"]) == (
        "demo-chat",
        "gpt-oss:120b-cloud",
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


def test_invalid_then_valid_retries_with_field_paths_only(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([INVALID, VALID])
    result = _call(db_url, stub)
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


def test_non_json_reply_is_retried_as_root_error(db_url: str) -> None:
    stub = StubOllama([f"not json {REPLY_SECRET}", VALID])
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    correction = stub.chat_bodies[1]["messages"][-1]["content"]
    assert "not a valid JSON object" in correction
    _assert_private(correction)


def test_retries_exhausted_raise_invalid_output_after_recording(
    db_url: str, sync_engine: Engine
) -> None:
    stub = StubOllama([INVALID, INVALID, INVALID])
    error = _call(db_url, stub)
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


def test_third_attempt_carries_only_the_latest_reply_and_correction(db_url: str) -> None:
    stub = StubOllama([INVALID, "[]", VALID])
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    third = stub.chat_bodies[2]["messages"]
    assert len(third) == 4
    assert third[-2] == {"role": "assistant", "content": "[]"}


def test_truncated_reply_fails_at_once_without_retry(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([_chat_reply('{"requirements": [', done_reason="length"), VALID])
    error = _call(db_url, stub)
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


def test_max_retries_zero_means_one_attempt(db_url: str) -> None:
    stub = StubOllama([INVALID])
    error = _call(db_url, stub, model_max_retries=0)
    assert isinstance(error, ModelOutputInvalidError)
    assert len(stub.chat_bodies) == 1


# --- errors -------------------------------------------------------------------------------


def test_connection_refused_raises_unavailable(db_url: str, sync_engine: Engine) -> None:
    async def refuse() -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    error = _call(db_url, StubOllama([refuse]))
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


def test_reply_without_message_content_is_bad_envelope(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([httpx.Response(200, json={"done": True}), VALID])
    error = _call(db_url, stub)
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
    exc: httpx.HTTPError,
    error_type: type[ModelGatewayError],
    outcome: str,
    code: str,
) -> None:
    async def fail() -> httpx.Response:
        raise exc

    error = _call(db_url, StubOllama([fail]))
    assert type(error) is error_type
    assert isinstance(error, ModelGatewayError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"]) == (outcome, code)


def test_server_error_raises_unavailable_without_retry(db_url: str, sync_engine: Engine) -> None:
    stub = StubOllama([httpx.Response(503, text=f"overloaded {PROMPT_SECRET}")])
    error = _call(db_url, stub)
    assert isinstance(error, ModelUnavailableError)
    assert len(stub.chat_bodies) == 1
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"]) == ("error", "http_503")
    _assert_private(str(error))


def test_slow_reply_raises_timeout(db_url: str, sync_engine: Engine) -> None:
    async def never() -> httpx.Response:
        await asyncio.Event().wait()  # never answers
        raise AssertionError("unreachable")

    error = _call(db_url, StubOllama([never]), _request(timeout_s=0.2))
    assert isinstance(error, ModelTimeoutError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("timeout", "timeout", 1)


def test_cancelled_call_writes_no_row(db_url: str, sync_engine: Engine) -> None:
    marker = f"cancelled-{new_id()}"

    async def scenario() -> None:
        settings = _settings(db_url)
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
    caplog: pytest.LogCaptureFixture, ok: bool
) -> None:
    caplog.set_level(logging.ERROR)
    replies: list[Any] = [VALID] if ok else [httpx.Response(503)]
    outcome = _call(UNREACHABLE_DB, StubOllama(replies), db_connect_timeout_s=1)
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
    replies: list[Any],
) -> None:
    caplog.set_level(logging.DEBUG)
    outcome = _call(db_url, StubOllama(replies))
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


def test_gateway_releases_slot_after_errors_and_cancellation(db_url: str) -> None:
    async def scenario() -> None:
        settings = _settings(db_url)
        engine: AsyncEngine = create_engine(settings)
        started = asyncio.Event()

        async def slow() -> httpx.Response:
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


def test_gateway_waits_for_a_slot_with_priority(db_url: str) -> None:
    """One slot held by a call; a background call queues, then an interactive one: the
    interactive call reaches the model first."""

    async def scenario() -> list[str]:
        settings = _settings(db_url)
        engine = create_engine(settings)
        release_first = asyncio.Event()
        first_started = asyncio.Event()
        seen: list[str] = []

        async def first() -> httpx.Response:
            first_started.set()
            await release_first.wait()
            return _chat_reply(VALID)

        class Recording(StubOllama):
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/chat":
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
