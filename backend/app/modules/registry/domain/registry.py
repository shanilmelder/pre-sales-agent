"""Agent Registry rules (Story 7.1): statuses, field validation, the seed ids and what a
config version records. Pure, no I/O."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid5

from app.modules.identity.actions import PermissionCategory, action_category
from app.platform.tool_gateway.catalogue import READ_TOOLS, is_read_tool

SUBJECT_TYPE = "registry.agent"
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_agent$")
AGENT_ID_MAX = 64
NAME_MAX = 120
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SEMVER_MAX = 32
TOOL_PERMISSION_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
)
"""A tool permission is an action name, `<module>.<entity>.<verb>`; since Story 5.4 one of
the ToolGateway's tools, and since Story 7.4 also an action of category `read`."""
TOOL_PERMISSIONS_MAX = 50
BUDGET_KEYS_MAX = 20
REASON_MAX = 500
"""A config version's reason (Story 7.3): required, trimmed, 1-500 characters."""
UNPINNED_DIGEST = "unpinned"
"""The model digest of a config version until digests are pinned (Story 7.2)."""

SEED_NAMESPACE = UUID("6f1c2f0e-4c1a-5b8e-9d3a-7e2b1c0a9f71")
"""The namespace of the deterministic `uuid5` ids of the seeded Agents and their config
version 1. The migration repeats this literal: it never imports the app."""


def agent_row_id(agent_id: str) -> UUID:
    """An Agent's row id, derived from its agent id."""
    return uuid5(SEED_NAMESPACE, agent_id)


def seed_config_version_id(agent_id: str) -> UUID:
    """The id of a seeded Agent's config version 1."""
    return uuid5(SEED_NAMESPACE, f"{agent_id}/config/1")


class AgentStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    EVAL_ONLY = "eval_only"
    """Behaves as `disabled` for runs (Story 7.1); evals use it later (Story 7.6)."""


def runs_tasks(status: AgentStatus | str) -> bool:
    """Only an `active` Agent gets new tasks; `disabled` and `eval_only` don't."""
    return status == AgentStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class ConfigVersion:
    """One immutable config version of an Agent."""

    id: UUID
    agent_id: str
    version: int
    semver: str
    model_profile: str
    model_digest: str
    prompt_version: int
    input_schema_version: int
    output_schema_version: int
    contract_version: str
    tool_permissions: tuple[str, ...]
    budgets: Mapping[str, Any] = field(hash=False)
    created_by: UUID | None
    """The administrator who created it; None for the versions the migration seeded."""
    created_at: datetime
    reason: str | None = None
    """Why an administrator created it (Story 7.3); None for seeded and earlier versions."""
    restored_from_version: int | None = None
    """The earlier version a restore copied (Story 7.3); None unless a restore."""

    @property
    def actor_id(self) -> str:
        """The trace actor of the agent at this version: `<agent_id>@<semver>`."""
        return f"{self.agent_id}@{self.semver}"


@dataclass(frozen=True, slots=True)
class RegisteredAgent:
    """An Agent with its status and its current (newest) config version."""

    id: UUID
    agent_id: str
    name: str
    status: AgentStatus
    row_version: int
    created_at: datetime
    current: ConfigVersion

    @property
    def runs_tasks(self) -> bool:
        return runs_tasks(self.status)


def _bounded(value: str, label: str, maximum: int) -> str:
    trimmed = value.strip()
    if "\x00" in trimmed:
        raise ValueError(f"The {label} contains characters that can't be saved.")
    if not trimmed:
        raise ValueError(f"The {label} is required.")
    if len(trimmed) > maximum:
        raise ValueError(f"The {label} must be at most {maximum:,} characters.")
    return trimmed


def agent_id(value: str) -> str:
    """A unique snake_case id ending in `_agent`, e.g. `security_agent`."""
    trimmed = _bounded(value, "agent id", AGENT_ID_MAX)
    if not AGENT_ID_RE.match(trimmed):
        raise ValueError(
            "The agent id must be lowercase snake_case ending in `_agent`, e.g. `security_agent`."
        )
    return trimmed


def agent_name(value: str) -> str:
    return _bounded(value, "name", NAME_MAX)


def reason(value: str) -> str:
    """Why a config version was created: required, trimmed, at most 500 characters."""
    return _bounded(value, "reason", REASON_MAX)


def semver(value: str) -> str:
    trimmed = _bounded(value, "semver", SEMVER_MAX)
    if not SEMVER_RE.match(trimmed):
        raise ValueError("The semver must be MAJOR.MINOR.PATCH, e.g. `0.2.0`.")
    return trimmed


class PermissionForbiddenForAgents(ValueError):
    """A tool permission that is an action name but not a `read` action that is also a
    ToolGateway tool (Story 7.4): a write, delete, send or approve action, a read that is
    no tool, or a name no action has."""


def grantable(name: str) -> bool:
    """Whether an Agent may hold `name`: a `read` action that is also a ToolGateway tool."""
    return action_category(name) == PermissionCategory.READ and is_read_tool(name)


def _forbidden(name: str) -> PermissionForbiddenForAgents:
    category = action_category(name)
    what = (
        "is not an action"
        if category is None
        else f"is a {category.value} action"
        if category != PermissionCategory.READ
        else "is a read action but not a ToolGateway tool"
    )
    return PermissionForbiddenForAgents(
        f"{name} {what}. Agents may only be granted these read tools: "
        f"{', '.join(sorted(n for n in READ_TOOLS if grantable(n)))}."
    )


def tool_permissions(values: Sequence[str]) -> tuple[str, ...]:
    """Distinct grantable tool names (`grantable`), in the order given. Raises
    `PermissionForbiddenForAgents` for any other action name, `ValueError` for a malformed
    one or too many."""
    if len(values) > TOOL_PERMISSIONS_MAX:
        raise ValueError(f"An agent can hold at most {TOOL_PERMISSIONS_MAX} tool permissions.")
    seen: list[str] = []
    for value in values:
        name = value.strip()
        if not TOOL_PERMISSION_RE.match(name):
            raise ValueError(
                "Each tool permission must be an action name, `<module>.<entity>.<verb>`."
            )
        if not grantable(name):
            raise _forbidden(name)
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def budgets(value: Mapping[str, Any]) -> dict[str, Any]:
    if len(value) > BUDGET_KEYS_MAX:
        raise ValueError(f"A config can set at most {BUDGET_KEYS_MAX} budgets.")
    return dict(value)
