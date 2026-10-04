"""The job type registry (AD-29): one `JobType` per `<module>.<verb>` job type.

A module registers each of its job types at import, the way the trace catalogue does:

    class ParseSource(JobPayload):
        source_id: UUID

    async def parse_source(ctx: JobContext, payload: ParseSource) -> None: ...

    PARSE_SOURCE = register(
        JobType(name="intake.parse_source", payload=ParseSource, handler=parse_source,
                priority="interactive")
    )

**Handlers must be idempotent.** Delivery is at least once: a worker that dies mid-run (or
whose lease expires) has its job reclaimed and run again, and a handler that times out may
already have done part of its work. Only the `succeeded` transition is written exactly once.

**Handlers must not block the event loop.** The timeout and the lease heartbeat run on the
same loop as the handler, so blocking or CPU-bound work (parsing, hashing large files, sync
I/O) goes to a subprocess or `asyncio.to_thread`; otherwise the timeout cannot fire and the
lease expires while the job is still running.

Handlers follow AD-25: they open their own Units of Work (`unit_of_work(ctx.engine)`) as
they need them, keep them short, and never hold one open across a model or HTTP call. The
queue never holds a transaction open while a handler runs.

Payloads hold ids and technical values only, never customer content (they are stored in
`platform_jobs.payload`, and job ids and types appear in logs).
"""

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

Priority = Literal["interactive", "background"]
# Stored in `platform_jobs.priority`; claims take lower ranks first.
PRIORITY_RANK: Mapping[Priority, int] = MappingProxyType({"interactive": 0, "background": 1})

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
JOB_TYPE_RE = re.compile(rf"^{_SEGMENT}\.{_SEGMENT}$")


class UnknownJobTypeError(LookupError):
    """A payload whose class is not registered. A programming error, so not a
    `ProblemError` (it surfaces as a 500)."""


class JobPayload(BaseModel):
    """Base for job payloads: frozen, and unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True, slots=True)
class JobContext:
    """What a handler gets besides its payload."""

    job_id: UUID
    job_type: str
    attempt: int
    """1 on the first run; counts every claim, including reclaims after a lost lease."""
    max_attempts: int
    opportunity_id: UUID | None
    engine: AsyncEngine
    """Open Units of Work on this with `app.platform.uow.unit_of_work`."""


type JobHandler[P: JobPayload] = Callable[[JobContext, P], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class JobType[P: JobPayload]:
    name: str
    payload: type[P]
    handler: JobHandler[P]
    priority: Priority = "background"
    timeout_s: float = 300.0
    max_attempts: int = 3
    backoff_base_s: float = 5.0
    backoff_cap_s: float = 300.0

    def __post_init__(self) -> None:
        if not JOB_TYPE_RE.match(self.name):
            raise ValueError(f"job type {self.name!r} must match <module>.<verb>")
        if self.payload.model_config.get("extra") != "forbid":
            raise ValueError(f"{self.payload.__name__} must forbid extra fields")
        if self.timeout_s <= 0 or self.max_attempts < 1:
            raise ValueError("timeout_s must be > 0 and max_attempts >= 1")
        if self.backoff_base_s < 0 or self.backoff_cap_s < self.backoff_base_s:
            raise ValueError("backoff must satisfy 0 <= backoff_base_s <= backoff_cap_s")

    @property
    def rank(self) -> int:
        """`platform_jobs.priority`: claims take lower ranks first."""
        return PRIORITY_RANK[self.priority]

    def backoff_s(self, attempts: int) -> float:
        """Delay before the next attempt after `attempts` failed ones: exponential, capped."""
        exponent = max(0, attempts - 1)
        if exponent >= 32:  # avoids huge floats; the cap applies long before this
            return self.backoff_cap_s
        return min(self.backoff_cap_s, self.backoff_base_s * 2.0**exponent)


_BY_NAME: dict[str, JobType[Any]] = {}
_BY_PAYLOAD: dict[type[JobPayload], JobType[Any]] = {}
REGISTRY: Mapping[str, JobType[Any]] = MappingProxyType(_BY_NAME)


def register[P: JobPayload](spec: JobType[P]) -> JobType[P]:
    """Add a job type. Names and payload classes are each registered once."""
    if spec.name in _BY_NAME:
        raise ValueError(f"job type {spec.name!r} is already registered")
    if spec.payload in _BY_PAYLOAD:
        raise ValueError(f"{spec.payload.__name__} is already the payload of another job type")
    _BY_NAME[spec.name] = spec
    _BY_PAYLOAD[spec.payload] = spec
    return spec


def get(name: str) -> JobType[Any]:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise UnknownJobTypeError(f"job type {name!r} is not registered") from None


def for_payload(payload: JobPayload) -> JobType[Any]:
    """The job type whose payload model is exactly `type(payload)`."""
    try:
        return _BY_PAYLOAD[type(payload)]
    except KeyError:
        name = type(payload).__name__
        raise UnknownJobTypeError(f"{name} is not a registered job payload") from None
