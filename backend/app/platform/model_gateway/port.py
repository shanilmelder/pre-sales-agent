"""The ModelGateway port: `complete_structured(request) -> StructuredResult[T]` (AD-8).

Provider-neutral. A request carries the messages, the Pydantic output model `T`, the profile
name, the priority, a timeout and the caller's metadata; the result carries the validated
object plus the call's tokens, latency, attempts and model digest.

**Privacy:** nothing here ever holds prompt or response text outside `Message.content` and
`StructuredResult.value`. Errors carry ids, codes and schema field paths only, so they are
safe to log and to store.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from app.platform.jobs.registry import Priority

Role = Literal["system", "user", "assistant"]
Outcome = Literal["ok", "invalid_output", "error", "timeout"]
OUTCOMES: tuple[Outcome, ...] = ("ok", "invalid_output", "error", "timeout")


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str

    def __repr__(self) -> str:  # never echo prompt text into logs or tracebacks
        return f"Message(role={self.role!r}, chars={len(self.content)})"


@dataclass(frozen=True, slots=True, kw_only=True)
class CallerMetadata:
    """Who is calling; recorded on the `platform_model_calls` row."""

    agent_id: str
    config_version: str
    run_id: UUID | None = None
    task_id: UUID | None = None
    opportunity_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredRequest[T: BaseModel]:
    messages: Sequence[Message]
    output_model: type[T]
    """The reply must validate as this model; its JSON Schema is sent as the format."""
    caller: CallerMetadata
    profile: str | None = None
    """A profile name (`profiles.MODEL_PROFILES`); None means the configured chat profile."""
    priority: Priority = "background"
    timeout_s: float | None = None
    """Timeout of each model request (attempt); None means `PSA_MODEL_TIMEOUT_S`."""

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("a model request needs at least one message")
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")

    def __repr__(self) -> str:
        return (
            f"StructuredRequest(output_model={self.output_model.__name__}, "
            f"messages={len(self.messages)}, profile={self.profile!r}, "
            f"priority={self.priority!r}, caller={self.caller!r})"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredResult[T: BaseModel]:
    value: T = field(repr=False)
    call_id: UUID
    """The `platform_model_calls` row of this call."""
    profile: str
    model: str
    model_digest: str
    """The model's digest from `/api/tags`, or `unknown`."""
    input_tokens: int
    output_tokens: int
    """Token counts summed over every attempt."""
    latency_ms: int
    """Wall time of all attempts, excluding the wait for a slot."""
    attempts: int


class ModelGatewayError(Exception):
    """Base of the gateway's typed errors. Raised after the call row is written."""

    outcome: Outcome = "error"
    error_code: str = "model_error"

    def __init__(self, message: str, *, call_id: UUID | None = None) -> None:
        super().__init__(message)
        self.call_id = call_id


class ModelUnavailableError(ModelGatewayError):
    """The model server could not be reached or answered with an error status."""

    outcome: Outcome = "error"

    def __init__(
        self, message: str, *, error_code: str = "unavailable", call_id: UUID | None = None
    ) -> None:
        super().__init__(message, call_id=call_id)
        self.error_code = error_code


class ModelTimeoutError(ModelGatewayError):
    """A model request exceeded its timeout."""

    outcome: Outcome = "timeout"
    error_code = "timeout"


class ModelOutputInvalidError(ModelGatewayError):
    """Every attempt returned output that failed schema validation (retries exhausted), or
    a reply was cut off (`error_code="truncated"`, not retried)."""

    outcome: Outcome = "invalid_output"
    error_code = "invalid_output"

    def __init__(
        self,
        message: str,
        *,
        field_paths: Sequence[str] = (),
        error_code: str = "invalid_output",
        call_id: UUID | None = None,
    ) -> None:
        super().__init__(message, call_id=call_id)
        self.field_paths = tuple(field_paths)
        self.error_code = error_code


class ModelGatewayPort(Protocol):
    """What agents depend on; tests substitute a fake."""

    async def complete_structured[T: BaseModel](
        self, request: StructuredRequest[T]
    ) -> StructuredResult[T]: ...
