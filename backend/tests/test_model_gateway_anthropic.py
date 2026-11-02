"""The Anthropic adapter, through `ModelGateway`, with the SDK's `httpx2` transport stubbed.

Every scenario of the provider's edge-case matrix runs end to end: profile, gateway, SDK,
request body, reply parsing, typed errors and the `platform_model_calls` row. No live model.
"""

import asyncio
import dataclasses
import json
import logging
import socket
from collections.abc import Awaitable, Callable
from typing import Any, get_args
from uuid import UUID

import anthropic
import httpx2
import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.agents.manifest import SCHEMA_VERSIONS
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import (
    CallerMetadata,
    EmbedRequest,
    Message,
    ModelGatewayError,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredRequest,
    StructuredResult,
)
from app.platform.model_gateway.profiles import EmbedProfile
from tests.conftest import run_async
from tests.test_model_gateway import SEEDED, resolve_seeded

PROFILE = "anthropic-opus-chat"
MODEL = "claude-opus-5-5"
API_KEY = "sk-ant-SECRET-key-5d2e"
PROMPT_SECRET = "PROMPT-SECRET-Acme-warehouse-7f3a"
REPLY_SECRET = "REPLY-SECRET-conveyor-91bc"
NO_RETRY = {"x-should-retry": "false"}


class Item(BaseModel):
    title: str
    priority: int


class Extraction(BaseModel):
    items: list[Item]
    summary: str


class Unsendable(BaseModel):
    value: Any


VALID = json.dumps({"items": [{"title": REPLY_SECRET, "priority": 1}], "summary": REPLY_SECRET})
INVALID = json.dumps({"items": [{"title": "x", "priority": REPLY_SECRET}]})


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _message(
    *content: dict[str, Any],
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_stub",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": list(content),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 11, "output_tokens": 7} if usage is None else usage,
        },
    )


Script = httpx2.Response | str | Callable[[], Awaitable[httpx2.Response]]


class Stub:
    """Answers `POST /v1/messages` from a script: a reply text or a whole response."""

    def __init__(self, *replies: Script) -> None:
        self.replies = list(replies)
        self.requests: list[httpx2.Request] = []
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if callable(reply):
            return await reply()
        return _message(_text(reply)) if isinstance(reply, str) else reply


def _request(**overrides: Any) -> StructuredRequest[Any]:
    fields: dict[str, Any] = {
        "messages": [
            Message(role="system", content="Extract the items."),
            Message(role="user", content=f"<data>{PROMPT_SECRET}</data>"),
        ],
        "output_model": Extraction,
        "caller": CallerMetadata(agent_id="intake_agent", config_version="0.1.0+p1"),
        "profile": PROFILE,
        "priority": "interactive",
        "timeout_s": 5,
    }
    return StructuredRequest(**(fields | overrides))


def _settings(db_url: str, **overrides: Any) -> Settings:
    fields: dict[str, Any] = {
        "database_url": db_url,
        "ollama_url": "http://ollama.test",
        "anthropic_api_key": API_KEY,
        "model_max_retries": 2,
    }
    return Settings(**(fields | overrides))


def _call(
    db_url: str,
    stub: Stub,
    request: StructuredRequest[Any] | None = None,
    **settings: Any,
) -> StructuredResult[Any] | ModelGatewayError:
    async def scenario() -> StructuredResult[Any] | ModelGatewayError:
        config = _settings(db_url, **settings)
        engine = create_engine(config)
        try:
            async with ModelGateway(
                config,
                engine,
                anthropic_transport=httpx2.MockTransport(stub),
                resolve_profile=resolve_seeded,
            ) as gateway:
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


def _assert_private(*texts: str) -> None:
    for text in texts:
        assert PROMPT_SECRET not in text
        assert REPLY_SECRET not in text
        assert API_KEY not in text


def _assert_error_private(error: ModelGatewayError) -> None:
    _assert_private(str(error), repr(error), repr(error.__cause__), repr(error.__context__))


# --- valid reply and request shape --------------------------------------------------------


def test_valid_reply_returns_result_and_records_the_call(db_url: str, sync_engine: Engine) -> None:
    stub = Stub(VALID)
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    assert result.value.summary == REPLY_SECRET
    assert (result.input_tokens, result.output_tokens, result.attempts) == (11, 7, 1)
    assert (result.profile, result.model, result.model_digest) == (PROFILE, MODEL, "unknown")
    row = _row(sync_engine, result.call_id)
    assert (row["profile"], row["model"], row["model_digest"]) == (PROFILE, MODEL, "unknown")
    assert (row["input_tokens"], row["output_tokens"]) == (11, 7)
    assert (row["outcome"], row["error_code"]) == ("ok", None)


def test_request_carries_the_profiles_settings_and_no_sampling_config(db_url: str) -> None:
    stub = Stub(VALID)
    _call(db_url, stub)
    [request] = stub.requests
    [body] = stub.bodies
    assert (request.method, request.url.path) == ("POST", "/v1/messages")
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    assert body["model"] == MODEL
    assert body["max_tokens"] == 16000
    assert body["system"] == "Extract the items."
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"] == {
        "type": "json_schema",
        "schema": anthropic.transform_schema(Extraction.model_json_schema()),
    }
    for key in ("temperature", "top_p", "top_k", "thinking", "stream"):
        assert key not in body


def test_called_via_the_registry_profile(db_url: str, sync_engine: Engine) -> None:
    stub = Stub(VALID)
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    assert _row(sync_engine, result.call_id)["profile"] == PROFILE
    assert stub.bodies[0]["model"] == MODEL


def test_unset_fields_are_omitted(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = dataclasses.replace(SEEDED[PROFILE], reasoning_effort=None, refusal_fallback=False)
    monkeypatch.setitem(SEEDED, PROFILE, plain)
    stub = Stub(VALID)
    _call(db_url, stub, _request(messages=[Message(role="user", content="hello")]))
    [body] = stub.bodies
    assert "system" not in body
    assert "fallbacks" not in body
    assert "effort" not in body["output_config"]
    assert "server-side-fallback" not in stub.requests[0].headers.get("anthropic-beta", "")


def test_several_system_messages_are_joined(db_url: str) -> None:
    stub = Stub(VALID)
    messages = [
        Message(role="system", content="One."),
        Message(role="system", content="Two."),
        Message(role="user", content="hello"),
    ]
    _call(db_url, stub, _request(messages=messages))
    assert stub.bodies[0]["system"] == "One.\n\nTwo."


# --- replies ------------------------------------------------------------------------------


def test_validation_retry_appends_the_turns_in_order(db_url: str, sync_engine: Engine) -> None:
    stub = Stub(INVALID, VALID)
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    assert result.attempts == 2
    assert (result.input_tokens, result.output_tokens) == (22, 14)
    first, second = stub.bodies
    assert second["messages"][:-2] == first["messages"]
    assert second["messages"][-2] == {"role": "assistant", "content": INVALID}
    assert second["messages"][-1]["role"] == "user"
    assert "items.0.priority" in second["messages"][-1]["content"]
    assert second["system"] == first["system"]
    assert _row(sync_engine, result.call_id)["attempts"] == 2


def test_only_text_blocks_form_the_content(db_url: str) -> None:
    half = len(VALID) // 2
    reply = _message(
        {"type": "thinking", "thinking": "", "signature": "sig"},
        _text(VALID[:half]),
        _text(VALID[half:]),
    )
    result = _call(db_url, Stub(reply))
    assert isinstance(result, StructuredResult)
    assert result.value.summary == REPLY_SECRET


def test_fallback_block_is_ignored(db_url: str) -> None:
    fallback = {
        "type": "fallback",
        "from": {"model": MODEL},
        "to": {"model": "claude-opus-4-8"},
        "trigger": {"type": "refusal", "category": None},
    }
    result = _call(db_url, Stub(_message(fallback, _text(VALID))))
    assert isinstance(result, StructuredResult)
    assert result.value.summary == REPLY_SECRET


@pytest.mark.parametrize(
    "response",
    [
        _message({"type": "thinking", "thinking": "", "signature": "sig"}),
        _message(),
        _message(_text("")),
        _message(_text(" \n")),
        httpx2.Response(200, json={"id": "msg_stub", "type": "message"}),
        httpx2.Response(200, json=[1, 2]),
        httpx2.Response(200, text="not json"),
    ],
    ids=["thinking_only", "empty", "empty_text", "blank_text", "no_content", "list", "not_json"],
)
def test_reply_without_text_is_bad_envelope(
    db_url: str, sync_engine: Engine, response: httpx2.Response
) -> None:
    stub = Stub(response, VALID)
    error = _call(db_url, stub)
    assert isinstance(error, ModelUnavailableError)
    assert len(stub.bodies) == 1
    assert _row(sync_engine, error.call_id)["error_code"] == "bad_envelope"


@pytest.mark.parametrize(
    "usage",
    ["nope", {}, {"input_tokens": "11", "output_tokens": -1}],
    ids=["not_object", "empty", "bad_values"],
)
def test_bad_usage_counts_as_zero(db_url: str, usage: Any) -> None:
    result = _call(db_url, Stub(_message(_text(VALID), usage=usage)))
    assert isinstance(result, StructuredResult)
    assert (result.input_tokens, result.output_tokens) == (0, 0)


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
@pytest.mark.parametrize(
    "content",
    [
        (_text('{"items": ['),),
        (_text(""),),
        ({"type": "thinking", "thinking": "", "signature": "sig"},),
    ],
    ids=["partial_text", "empty_text", "thinking_only"],
)
def test_truncated_reply_fails_at_once(
    db_url: str, sync_engine: Engine, content: tuple[dict[str, Any], ...], stop_reason: str
) -> None:
    stub = Stub(_message(*content, stop_reason=stop_reason), VALID)
    error = _call(db_url, stub)
    assert isinstance(error, ModelOutputInvalidError)
    assert error.error_code == "truncated"
    assert len(stub.bodies) == 1
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["output_tokens"]) == (
        "invalid_output",
        "truncated",
        7,
    )


def test_refusal_uses_no_content_and_is_not_retried(db_url: str, sync_engine: Engine) -> None:
    stub = Stub(_message(_text(REPLY_SECRET), stop_reason="refusal"), VALID)
    error = _call(db_url, stub)
    assert isinstance(error, ModelOutputInvalidError)
    assert error.error_code == "refusal"
    assert len(stub.bodies) == 1
    _assert_error_private(error)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("invalid_output", "refusal", 1)
    assert (row["input_tokens"], row["output_tokens"]) == (11, 7)


def test_reply_is_recorded_under_the_model_that_served_it(
    db_url: str, sync_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    served_by = "claude-opus-4-8"
    reply = _message(_text(VALID))
    reply = httpx2.Response(200, json=reply.json() | {"model": served_by})
    result = _call(db_url, Stub(reply))
    assert isinstance(result, StructuredResult)
    assert result.model == served_by
    assert _row(sync_engine, result.call_id)["model"] == served_by
    [record] = [r for r in caplog.records if r.getMessage() == "model_call.completed"]
    assert record.__dict__["model"] == served_by


# --- errors -------------------------------------------------------------------------------


@pytest.mark.parametrize("key", [None, "", " \t\n"], ids=["unset", "empty", "whitespace"])
def test_missing_key_sends_nothing(db_url: str, sync_engine: Engine, key: str | None) -> None:
    stub = Stub(VALID)
    error = _call(db_url, stub, anthropic_api_key=key)
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "missing_api_key"
    assert stub.requests == []
    assert _row(sync_engine, error.call_id)["error_code"] == "missing_api_key"


def test_missing_key_ignores_the_sdks_ambient_credentials(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", API_KEY)
    stub = Stub(VALID)
    error = _call(db_url, stub, anthropic_api_key=None)
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "missing_api_key"
    assert stub.requests == []


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_status_error_is_unavailable_and_private(
    db_url: str, sync_engine: Engine, status: int
) -> None:
    body = {"type": "error", "error": {"type": "x", "message": f"bad {PROMPT_SECRET}"}}
    response = httpx2.Response(status, json=body, headers=NO_RETRY)
    error = _call(db_url, Stub(response))
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == f"http_{status}"
    _assert_error_private(error)
    assert _row(sync_engine, error.call_id)["error_code"] == f"http_{status}"


def test_sdk_retries_5xx_within_one_attempt(db_url: str, sync_engine: Engine) -> None:
    stub = Stub(httpx2.Response(503), VALID)
    result = _call(db_url, stub)
    assert isinstance(result, StructuredResult)
    assert len(stub.requests) == 2
    assert _row(sync_engine, result.call_id)["attempts"] == 1


def test_timeout_bounds_the_attempt_including_sdk_retries(db_url: str, sync_engine: Engine) -> None:
    async def never() -> httpx2.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    error = _call(db_url, Stub(never), _request(timeout_s=0.2))
    assert isinstance(error, ModelTimeoutError)
    row = _row(sync_engine, error.call_id)
    assert (row["outcome"], row["error_code"], row["attempts"]) == ("timeout", "timeout", 1)


def test_sdk_timeout_is_a_timeout(db_url: str, sync_engine: Engine) -> None:
    async def slow() -> httpx2.Response:
        raise httpx2.ReadTimeout("slow")

    error = _call(db_url, Stub(slow, slow, slow))
    assert isinstance(error, ModelTimeoutError)
    assert _row(sync_engine, error.call_id)["outcome"] == "timeout"


def test_connection_failure_is_connection(db_url: str, sync_engine: Engine) -> None:
    async def refuse() -> httpx2.Response:
        raise httpx2.ConnectError(f"refused {PROMPT_SECRET}")

    error = _call(db_url, Stub(refuse, refuse, refuse))
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "connection"
    _assert_error_private(error)
    assert _row(sync_engine, error.call_id)["error_code"] == "connection"


def test_schema_the_sdk_cannot_transform_is_a_typed_error(db_url: str) -> None:
    stub = Stub(VALID)
    error = _call(db_url, stub, _request(output_model=Unsendable))
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "unsupported_schema"
    assert stub.requests == []


def test_embed_is_unsupported_and_sends_nothing(
    db_url: str, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = EmbedProfile(name="claude-embed", model=MODEL, dims=4, provider="anthropic")
    monkeypatch.setattr("app.platform.model_gateway.gateway.get_embed_profile", lambda _: profile)
    stub = Stub(VALID)

    async def scenario() -> ModelGatewayError:
        config = _settings(db_url)
        engine = create_engine(config)
        try:
            async with ModelGateway(
                config, engine, anthropic_transport=httpx2.MockTransport(stub)
            ) as gateway:
                request = EmbedRequest(
                    texts=[PROMPT_SECRET],
                    caller=CallerMetadata(agent_id="test.embed", config_version="0"),
                )
                with pytest.raises(ModelGatewayError) as info:
                    await gateway.embed(request)
                return info.value
        finally:
            await engine.dispose()

    error = run_async(scenario())
    assert isinstance(error, ModelUnavailableError)
    assert error.error_code == "embed_unsupported"
    assert stub.requests == []
    assert _row(sync_engine, error.call_id)["error_code"] == "embed_unsupported"


# --- the SDK client ------------------------------------------------------------------------


def test_ambient_base_url_is_ignored(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://elsewhere.test")
    stub = Stub(VALID)
    _call(db_url, stub)
    assert stub.requests[0].url.host == "api.anthropic.com"


def test_keyed_gateway_without_a_transport_keeps_tcp_keepalive(db_url: str) -> None:
    async def scenario() -> Any:
        config = _settings(db_url)
        engine = create_engine(config)
        try:
            async with ModelGateway(config, engine) as gateway:
                assert gateway._anthropic_client is not None
                transport: Any = gateway._anthropic_client._client._transport
                return transport._pool._socket_options
        finally:
            await engine.dispose()

    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in run_async(scenario())


# --- privacy ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "replies",
    [
        (VALID,),
        (INVALID, INVALID, INVALID),
        (httpx2.Response(500, text=REPLY_SECRET, headers=NO_RETRY),),
        (_message(_text(REPLY_SECRET), stop_reason="refusal"),),
    ],
    ids=["ok", "invalid_output", "error", "refusal"],
)
def test_no_prompt_reply_or_key_in_logs_rows_or_errors(
    db_url: str,
    sync_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    replies: tuple[Script, ...],
) -> None:
    caplog.set_level(logging.DEBUG)
    outcome = _call(db_url, Stub(*replies))
    _assert_private(json.dumps(_row(sync_engine, outcome.call_id), default=str), repr(outcome))
    if isinstance(outcome, ModelGatewayError):
        _assert_error_private(outcome)
    assert any(r.getMessage().startswith("model_call.") for r in caplog.records)
    for record in caplog.records:
        _assert_private(record.getMessage(), json.dumps(record.__dict__, default=str))


# --- profile, config and schemas ----------------------------------------------------------


def test_key_stays_out_of_the_settings_repr(db_url: str) -> None:
    assert API_KEY not in repr(_settings(db_url))


def _output_models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for item in SCHEMA_VERSIONS:
        if item.kind == "output":
            models.extend(get_args(item.model) or (item.model,))
    return models


def _walk(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [found for item in node for found in _walk(item)]
    if isinstance(node, dict):
        return [node, *(found for value in node.values() for found in _walk(value))]
    return []


def test_all_twelve_agent_output_models_are_found() -> None:
    assert len(_output_models()) == 12


@pytest.mark.parametrize("model", _output_models(), ids=lambda model: model.__name__)
def test_agent_output_schema_passes_transform_schema(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()
    strict = anthropic.transform_schema(schema)
    assert strict["type"] == "object"
    for node in _walk(strict):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
        for keyword in ("minimum", "maximum", "minLength", "maxLength", "pattern"):
            # A dict here is a property that happens to share the keyword's name.
            assert not isinstance(node.get(keyword), int | float | str)
