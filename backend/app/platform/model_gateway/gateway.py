"""`ModelGateway`: the governed path to a model (AD-8).

One call = wait for a slot on the priority semaphore, then up to `1 + PSA_MODEL_MAX_RETRIES`
attempts against the adapter, validating each reply with `T.model_validate_json`. An
invalid reply is retried with that reply (as the assistant turn) plus a corrective user
message naming only the failing field paths; neither is logged or stored. A truncated reply
(`done_reason: "length"`) fails at once as `invalid_output` / `truncated`. The slot is
released, then the `platform_model_calls` row is written in its own Unit of Work (none is
open during the HTTP call, AD-25), then the result is returned or the typed error raised.
If the row write fails it is logged (`model_call.record_failed`) and the call's own result
or error still wins. A caller cancelled mid-call gets no row.

Create one gateway per process (the semaphore is per gateway) and close it with `aclose()`
or `async with`. Only the worker makes model calls; the `api` process never does.
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
from app.platform.logging import get_logger
from app.platform.model_gateway.models import PlatformModelCall
from app.platform.model_gateway.ollama import OllamaAdapter
from app.platform.model_gateway.port import (
    Message,
    ModelGatewayError,
    ModelOutputInvalidError,
    Outcome,
    StructuredRequest,
    StructuredResult,
)
from app.platform.model_gateway.profiles import ModelProfile, get_profile
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
        self._client = httpx.AsyncClient(base_url=settings.ollama_url, transport=transport)
        self._adapter = OllamaAdapter(self._client)
        self._semaphore = PrioritySemaphore(settings.model_slots)

    @property
    def semaphore(self) -> PrioritySemaphore:
        return self._semaphore

    async def aclose(self) -> None:
        await self._client.aclose()

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
        profile = get_profile(request.profile or self._settings.model_profile_chat)
        timeout_s = request.timeout_s or self._settings.model_timeout_s
        call_id = new_id()
        async with self._semaphore.slot(request.priority):
            run = await self._attempt_all(request, profile, timeout_s)
        digest = await self._adapter.digest(profile.model)
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
        try:
            await self._record(request, profile, call_id, digest, run, outcome, error_code)
        except Exception as exc:
            # Losing the record must not replace the model's result or typed error.
            _log.error(
                "model_call.record_failed",
                extra={"call_id": str(call_id), "exc_type": type(exc).__name__},
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
                    reply = await self._adapter.chat(profile, messages, schema, timeout_s)
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

    async def _record[T: BaseModel](
        self,
        request: StructuredRequest[T],
        profile: ModelProfile,
        call_id: UUID,
        digest: str,
        run: _Run[T],
        outcome: Outcome,
        error_code: str | None,
    ) -> None:
        caller = request.caller
        async with unit_of_work(self._engine) as uow:
            uow.session.add(
                PlatformModelCall(
                    id=call_id,
                    agent_id=caller.agent_id,
                    config_version=caller.config_version,
                    run_id=caller.run_id,
                    task_id=caller.task_id,
                    opportunity_id=caller.opportunity_id,
                    profile=profile.name,
                    model=profile.model,
                    model_digest=digest,
                    priority=request.priority,
                    input_tokens=run.input_tokens,
                    output_tokens=run.output_tokens,
                    latency_ms=run.latency_ms,
                    attempts=run.attempts,
                    outcome=outcome,
                    error_code=error_code,
                )
            )
