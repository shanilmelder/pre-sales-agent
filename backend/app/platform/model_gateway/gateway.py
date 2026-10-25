"""`ModelGateway`: the governed path to a model (AD-8).

One call = wait for a slot on the priority semaphore, then up to `1 + PSA_MODEL_MAX_RETRIES`
attempts against the profile's adapter (`ModelProfile.provider`: `ollama` or `openai`),
validating each reply with `T.model_validate_json`. An invalid reply is retried with that
reply (as the assistant turn) plus a corrective user message naming only the failing field
paths; neither is logged or stored. A truncated reply (`done_reason` / `finish_reason`
`length`) fails at once as `invalid_output` / `truncated`. The slot is released, then the
`platform_model_calls` row is written in its own Unit of Work (none is open during the HTTP
call, AD-25), then the result is returned or the typed error raised. If the row write fails
it is logged (`model_call.record_failed`) and the call's own result or error still wins.
A caller cancelled mid-call gets no row.

`embed(request)` (Story 3.3) takes a slot the same way, sends the texts in batches of the
embedding profile's `batch_size` (one adapter request each, not retried: the caller's job
retries), checks that every vector has the profile's `dims`, and writes one
`platform_model_calls` row for the whole call (`output_tokens` 0). The texts are never logged.

Create one gateway per process (the semaphore is per gateway) and close it with `aclose()`
or `async with`. The worker makes every chat and Source-embedding call; the `api` process
makes embedding calls only (Knowledge search queries, Story 3.3) and never a chat call.
"""

import re
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.config import Settings
from app.platform.ids import new_id
from app.platform.jobs.registry import Priority
from app.platform.logging import get_logger
from app.platform.model_gateway.adapter import ChatAdapter
from app.platform.model_gateway.models import PlatformModelCall
from app.platform.model_gateway.ollama import OllamaAdapter
from app.platform.model_gateway.openai_compat import OpenAICompatAdapter
from app.platform.model_gateway.port import (
    CallerMetadata,
    EmbedRequest,
    Message,
    ModelGatewayError,
    ModelOutputInvalidError,
    Outcome,
    StructuredRequest,
    StructuredResult,
)
from app.platform.model_gateway.profiles import (
    ModelProfile,
    Provider,
    get_embed_profile,
    get_profile,
    resolve_profile,
)
from app.platform.model_gateway.semaphore import PrioritySemaphore
from app.platform.uow import unit_of_work

_log = get_logger(__name__)
ROOT_PATH = "$"
_MAX_PATHS = 20
# Location parts that look like schema field names are kept; anything else (dict keys the
# model invented, which could be content) is masked.
_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def field_paths(exc: ValidationError) -> list[str]:
    """The failing locations of a validation error as dotted paths, without any input."""
    paths: list[str] = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        parts: list[str] = []
        for part in error["loc"]:
            if isinstance(part, int):
                parts.append(str(part))
            else:
                parts.append(part if _FIELD_NAME.match(part) else "<key>")
        path = ".".join(parts) or ROOT_PATH
        if path not in paths:
            paths.append(path)
    return paths[:_MAX_PATHS]


def corrective_message(paths: list[str]) -> Message:
    if paths == [ROOT_PATH]:
        problem = "Your previous reply was not a valid JSON object for the required schema."
    else:
        problem = (
            "Your previous reply did not match the required JSON schema. "
            f"Fields with errors: {', '.join(paths)}."
        )
    return Message(
        role="user",
        content=f"{problem} Reply again with only a JSON object that matches the schema exactly.",
    )


@dataclass(slots=True)
class _Run[T: BaseModel]:
    value: T | None = None
    error: ModelGatewayError | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    latency_ms: int = 0


class ModelGateway:
    def __init__(
        self,
        settings: Settings,
        engine: AsyncEngine,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`transport` replaces the network (tests pass an `httpx.MockTransport`)."""
        self._settings = settings
        self._engine = engine
        get_profile(settings.model_profile_chat)  # fail fast on an unknown profile
        get_embed_profile(settings.model_profile_embed)
        ollama_client = httpx.AsyncClient(base_url=settings.ollama_url, transport=transport)
        key = settings.openai_api_key
        api_key = key.get_secret_value().strip() if key else ""  # whitespace-only = unset
        openai_client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
            transport=transport,
        )
        self._clients = (ollama_client, openai_client)
        self._adapters: dict[Provider, ChatAdapter] = {
            "ollama": OllamaAdapter(ollama_client),
            "openai": OpenAICompatAdapter(openai_client),
        }
        self._semaphore = PrioritySemaphore(settings.model_slots)

    def _profile(self, name: str) -> ModelProfile:
        """The named profile as called (`resolve_profile`), so the request, the call record
        and the logs all name the model actually called."""
        return resolve_profile(
            name,
            openai_model=self._settings.openai_model,
            openai_reasoning_effort=self._settings.openai_reasoning_effort,
        )

    @property
    def semaphore(self) -> PrioritySemaphore:
        return self._semaphore

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def complete_structured[T: BaseModel](
        self, request: StructuredRequest[T]
    ) -> StructuredResult[T]:
        profile = self._profile(request.profile or self._settings.model_profile_chat)
        timeout_s = request.timeout_s or self._settings.model_timeout_s
        call_id = new_id()
        async with self._semaphore.slot(request.priority):
            run = await self._attempt_all(request, profile, timeout_s)
        digest = await self._adapters[profile.provider].digest(profile.model)
        outcome: Outcome = run.error.outcome if run.error else "ok"
        error_code = run.error.error_code if run.error else None
        log_fields = {
            "call_id": str(call_id),
            "agent_id": request.caller.agent_id,
            "config_version": request.caller.config_version,
            "run_id": request.caller.run_id and str(request.caller.run_id),
            "task_id": request.caller.task_id and str(request.caller.task_id),
            "opportunity_id": request.caller.opportunity_id and str(request.caller.opportunity_id),
            "profile": profile.name,
            "model": profile.model,
            "priority": request.priority,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "latency_ms": run.latency_ms,
            "attempts": run.attempts,
            "outcome": outcome,
            "error_code": error_code,
        }
        await self._record(
            caller=request.caller,
            priority=request.priority,
            profile=profile.name,
            model=profile.model,
            call_id=call_id,
            digest=digest,
            run=run,
            outcome=outcome,
            error_code=error_code,
        )
        if run.error is not None:
            _log.warning("model_call.failed", extra=log_fields)
            run.error.call_id = call_id
            raise run.error
        _log.info("model_call.completed", extra=log_fields)
        assert run.value is not None
        return StructuredResult(
            value=run.value,
            call_id=call_id,
            profile=profile.name,
            model=profile.model,
            model_digest=digest,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            latency_ms=run.latency_ms,
            attempts=run.attempts,
        )

    async def _attempt_all[T: BaseModel](
        self, request: StructuredRequest[T], profile: ModelProfile, timeout_s: float
    ) -> _Run[T]:
        adapter = self._adapters[profile.provider]
        schema = request.output_model.model_json_schema()
        run: _Run[T] = _Run()
        retry: list[Message] = []  # the invalid reply and the corrective message
        paths: list[str] = []
        started = time.perf_counter()
        try:
            for _ in range(1 + self._settings.model_max_retries):
                messages = list(request.messages)
                messages.extend(retry)
                run.attempts += 1
                try:
                    reply = await adapter.chat(profile, messages, schema, timeout_s)
                except ModelGatewayError as exc:
                    run.error = exc
                    return run
                run.input_tokens += reply.input_tokens
                run.output_tokens += reply.output_tokens
                if reply.truncated:
                    run.error = ModelOutputInvalidError(
                        "The model's output was cut off (length limit).",
                        error_code="truncated",
                    )
                    return run
                try:
                    run.value = request.output_model.model_validate_json(reply.content)
                    return run
                except ValidationError as exc:
                    paths = field_paths(exc)
                    retry = [
                        Message(role="assistant", content=reply.content),
                        corrective_message(paths),
                    ]
            run.error = ModelOutputInvalidError(
                f"The model's output failed validation after {run.attempts} attempts.",
                field_paths=paths,
            )
            return run
        finally:
            run.latency_ms = round((time.perf_counter() - started) * 1000)

    async def embed(self, request: EmbedRequest) -> list[list[float]]:
        profile = get_embed_profile(request.profile or self._settings.model_profile_embed)
        timeout_s = request.timeout_s or self._settings.model_timeout_s
        call_id = new_id()
        vectors: list[list[float]] = []
        run: _Run[BaseModel] = _Run()
        adapter = self._adapters[profile.provider]
        texts = list(request.texts)
        async with self._semaphore.slot(request.priority):
            started = time.perf_counter()
            try:
                for offset in range(0, len(texts), profile.batch_size):
                    run.attempts += 1
                    batch = texts[offset : offset + profile.batch_size]
                    try:
                        reply = await adapter.embed(profile, batch, timeout_s)
                    except ModelGatewayError as exc:
                        run.error = exc
                        break
                    run.input_tokens += reply.input_tokens
                    vectors.extend(reply.vectors)
            finally:
                run.latency_ms = round((time.perf_counter() - started) * 1000)
        digest = await adapter.digest(profile.model)
        outcome: Outcome = run.error.outcome if run.error else "ok"
        error_code = run.error.error_code if run.error else None
        await self._record(
            caller=request.caller,
            priority=request.priority,
            profile=profile.name,
            model=profile.model,
            call_id=call_id,
            digest=digest,
            run=run,
            outcome=outcome,
            error_code=error_code,
        )
        log_fields = {
            "call_id": str(call_id),
            "agent_id": request.caller.agent_id,
            "profile": profile.name,
            "model": profile.model,
            "priority": request.priority,
            "texts": len(texts),
            "input_tokens": run.input_tokens,
            "latency_ms": run.latency_ms,
            "requests": run.attempts,
            "outcome": outcome,
            "error_code": error_code,
        }
        if run.error is not None:
            _log.warning("model_call.embed_failed", extra=log_fields)
            run.error.call_id = call_id
            raise run.error
        _log.info("model_call.embedded", extra=log_fields)
        return vectors

    async def _record[T: BaseModel](
        self,
        *,
        caller: CallerMetadata,
        priority: Priority,
        profile: str,
        model: str,
        call_id: UUID,
        digest: str,
        run: _Run[T],
        outcome: Outcome,
        error_code: str | None,
    ) -> None:
        """Write the call's `platform_model_calls` row in its own Unit of Work. A failed
        write is logged and swallowed: it must not replace the call's result or error."""
        try:
            async with unit_of_work(self._engine) as uow:
                uow.session.add(
                    PlatformModelCall(
                        id=call_id,
                        agent_id=caller.agent_id,
                        config_version=caller.config_version,
                        run_id=caller.run_id,
                        task_id=caller.task_id,
                        opportunity_id=caller.opportunity_id,
                        profile=profile,
                        model=model,
                        model_digest=digest,
                        priority=priority,
                        input_tokens=run.input_tokens,
                        output_tokens=run.output_tokens,
                        latency_ms=run.latency_ms,
                        attempts=run.attempts,
                        outcome=outcome,
                        error_code=error_code,
                    )
                )
        except Exception as exc:
            _log.error(
                "model_call.record_failed",
                extra={"call_id": str(call_id), "exc_type": type(exc).__name__},
            )
