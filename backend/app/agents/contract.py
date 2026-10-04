"""The agent contract: `AgentResult`, the `Agent` interface and `AgentConfig`.

Agents only propose. An agent's `run(task)` returns an `AgentResult`; the owning module's
`accept_*` command validates it (including that every Evidence ref resolves) and writes it.
Agent-specific output goes in `extensions[<agent_id>]`.

`AgentConfig` is defined in code per agent; its `actor_id` (`<agent_id>@<semver>`) is the
actor recorded in trace events. Prompts live at `agents/<agent_id>/prompts/v<N>.md`, where N
is `prompt_version`.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.platform.model_gateway.profiles import get_profile

CONTRACT_VERSION: Literal["1"] = "1"
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Span(_Contract):
    """Unicode code-point offsets `[start, end)` into the cited text."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("span end must not be before its start")
        return self


class EvidenceRef(_Contract):
    """A reference to evidence: `{kind, id, version?, span?}`. Resolved on acceptance."""

    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    id: UUID
    version: int | None = Field(default=None, ge=1)
    span: Span | None = None


class Finding(_Contract):
    statement: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Assumption(_Contract):
    statement: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Unknown(_Contract):
    question: str = Field(min_length=1)


class Risk(_Contract):
    statement: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    evidence: list[EvidenceRef] = Field(default_factory=list)


class AgentResult(_Contract):
    contract_version: Literal["1"] = CONTRACT_VERSION
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    unknowns: list[Unknown] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    recommendation: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: str = Field(min_length=1)
    needs_human_review: bool
    extensions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Agent-specific output as plain JSON objects, keyed by the producing agent's id. A model
    instance is stored as its JSON dump; the owning module re-validates its own schema."""

    @field_validator("extensions", mode="before")
    @classmethod
    def _dump_models(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for key, item in value.items()
            }
        return value

    @field_validator("extensions")
    @classmethod
    def _keys_are_agent_ids(cls, value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        for key in value:
            if not AGENT_ID_RE.match(key):
                raise ValueError(f"extension key {key!r} is not an agent id")
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentConfig:
    """An agent's configuration, defined in code (the DB-owned registry comes later)."""

    agent_id: str
    semver: str
    prompt_version: int
    """N in `agents/<agent_id>/prompts/v<N>.md`."""
    profile: str
    """The ModelGateway profile name the agent calls; must be a defined profile."""

    def __post_init__(self) -> None:
        if not AGENT_ID_RE.match(self.agent_id):
            raise ValueError(f"agent_id {self.agent_id!r} must be snake_case")
        if not SEMVER_RE.match(self.semver):
            raise ValueError(f"semver {self.semver!r} must be MAJOR.MINOR.PATCH")
        if self.prompt_version < 1:
            raise ValueError("prompt_version must be >= 1")
        get_profile(self.profile)  # raises UnknownModelProfileError

    @property
    def actor_id(self) -> str:
        """The trace actor id: `<agent_id>@<semver>`."""
        return f"{self.agent_id}@{self.semver}"


class Agent[TaskT](Protocol):
    """An agent proposes; it never writes. Implementations are stateless across runs."""

    @property
    def config(self) -> AgentConfig: ...

    async def run(self, task: TaskT) -> AgentResult: ...
