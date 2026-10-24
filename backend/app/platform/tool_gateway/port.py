"""The ToolGateway's values (Story 5.4): the call context and the three outcomes.

Outcomes are values, never exceptions that fail the task: `ToolResult` (the data),
`ToolDenied(reason)` (the call was refused, nothing was read) and `ToolFailed(reason)` (the
research fetch failed; nothing was stored). Reasons are codes only, safe to log and store.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

DenyReason = Literal["tool_not_permitted", "out_of_scope", "unknown_tool", "not_allowlisted"]
DENY_REASONS: tuple[DenyReason, ...] = (
    "tool_not_permitted",
    "out_of_scope",
    "unknown_tool",
    "not_allowlisted",
)
FailReason = Literal[
    "timeout",
    "http_error",
    "too_large",
    "unsupported_content",
    "too_many_redirects",
    "parse_failed",
]
FAIL_REASONS: tuple[FailReason, ...] = (
    "timeout",
    "http_error",
    "too_large",
    "unsupported_content",
    "too_many_redirects",
    "parse_failed",
)
CallOutcome = Literal["ok", "denied", "failed"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolContext:
    """Who calls and for which task. Handlers take the Opportunity from here, never from
    the arguments: every call is scoped to `opportunity_id`."""

    agent_id: str
    semver: str
    config_version_id: UUID
    tool_permissions: frozenset[str]
    """The tools the pinned config version grants (registry `tool_permissions`)."""
    opportunity_id: UUID
    run_id: UUID | None = None
    task_id: UUID | None = None

    @property
    def actor_id(self) -> str:
        """The trace actor: `<agent_id>@<semver>`."""
        return f"{self.agent_id}@{self.semver}"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the tool read: handler-defined records (they may hold customer text; never
    logged or stored by the gateway). `http_status`: the research fetch's final status."""

    items: Sequence[Any] = field(default=(), repr=False)
    http_status: int | None = None

    @property
    def result_count(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class ToolDenied:
    reason: DenyReason


@dataclass(frozen=True, slots=True)
class ToolFailed:
    reason: FailReason
    http_status: int | None = None


type ToolOutcome = ToolResult | ToolDenied | ToolFailed


def outcome_code(outcome: ToolOutcome) -> CallOutcome:
    if isinstance(outcome, ToolResult):
        return "ok"
    return "denied" if isinstance(outcome, ToolDenied) else "failed"
