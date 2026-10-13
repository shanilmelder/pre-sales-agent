"""Read and write models for the Agent Registry (Story 7.1)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.registry.domain.registry import AgentStatus


class AgentConfigVersion(BaseModel):
    """One immutable config version of an Agent. `model_digest` is `unpinned` until digests
    are pinned (Story 7.2); `created_by_id` is null for the versions the migration seeded."""

    id: str
    agent_id: str
    version: int = Field(ge=1)
    semver: str
    model_profile: str
    model_digest: str
    prompt_version: int = Field(ge=1)
    input_schema_version: int = Field(ge=1)
    output_schema_version: int = Field(ge=1)
    contract_version: str
    tool_permissions: list[str]
    budgets: dict[str, Any]
    created_by_id: str | None
    created_at: datetime


class AgentConfigVersionList(BaseModel):
    """An Agent's config versions, newest first."""

    items: list[AgentConfigVersion]


class RegistryAgent(BaseModel):
    """An Agent with its status and current (newest) config version. Only an `active` Agent
    gets new tasks; `disabled` and `eval_only` don't."""

    id: str
    agent_id: str
    name: str
    status: AgentStatus
    row_version: int
    created_at: datetime
    current_config: AgentConfigVersion


class RegistryAgentList(BaseModel):
    items: list[RegistryAgent]


class NewAgentConfig(BaseModel):
    """A config version. The prompt, both schema versions and the model profile must be in
    the deployed manifest (422 `registry_config_not_deployed`), and the output schema must be
    written for the deployed `AgentResult` contract version (422
    `registry_config_incompatible_contract`). `tool_permissions`: action names
    (`<module>.<entity>.<verb>`), at most 50; `budgets`: at most 20 keys."""

    model_config = ConfigDict(extra="forbid")

    semver: StrictStr
    model_profile: StrictStr
    prompt_version: int = Field(ge=1, le=1_000_000)
    input_schema_version: int = Field(ge=1, le=1_000_000)
    output_schema_version: int = Field(ge=1, le=1_000_000)
    tool_permissions: list[StrictStr] = Field(default_factory=list)
    budgets: dict[str, Any] = Field(default_factory=dict)


class NewAgent(BaseModel):
    """Register an Agent with its config version 1. `agent_id`: unique, lowercase snake_case
    ending in `_agent`; `name`: 1-120 characters."""

    model_config = ConfigDict(extra="forbid")

    agent_id: StrictStr
    name: StrictStr
    config: NewAgentConfig


class AgentStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
