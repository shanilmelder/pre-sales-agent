"""Read and write models for the Agent Registry (Story 7.1) and its evaluation results (Story
7.6)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.registry.domain.registry import AgentStatus


class AgentConfigVersion(BaseModel):
    """One immutable config version of an Agent. `model_digest` is `unpinned` until digests
    are pinned (Story 7.2); `created_by_id` and `created_by_name` are null for the versions
    the migration seeded. `reason` is null for seeded and earlier versions (Story 7.3);
    `restored_from_version` is the earlier version a restore copied, else null."""

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
    created_by_name: str | None
    reason: str | None
    restored_from_version: int | None
    created_at: datetime


class AgentConfigVersionList(BaseModel):
    """An Agent's config versions, newest first."""

    items: list[AgentConfigVersion]


class EffectiveModel(BaseModel):
    """The model profile and model an Agent's current config version actually calls in this
    deployment. `profile` is `PSA_MODEL_PROFILE_CHAT` when that local-dev override is set
    (`overridden`), else the version's pinned `model_profile`. `model` is the profile's
    model, after `PSA_OPENAI_MODEL` for an `openai` provider profile; null when the profile
    is not defined in this deployment."""

    profile: str
    model: str | None
    overridden: bool


class RegistryAgent(BaseModel):
    """An Agent with its status and current (newest) config version. Only an `active` Agent
    gets new tasks; `disabled` and `eval_only` don't. `effective_model`: what the current
    config version calls here, which a local-dev override can make differ from its pinned
    profile."""

    id: str
    agent_id: str
    name: str
    status: AgentStatus
    row_version: int
    created_at: datetime
    current_config: AgentConfigVersion
    effective_model: EffectiveModel


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


class NewAgentConfigVersion(NewAgentConfig):
    """A new config version of an existing Agent (Story 7.3). `reason`: required, trimmed,
    1-500 characters. `restored_from_version`: set when the version restores an earlier one
    of the same Agent (422 when the Agent has no such version); its fields are the ones
    given here, which the client copies from that version."""

    reason: StrictStr
    restored_from_version: int | None = Field(default=None, ge=1, le=1_000_000)


PermissionCategoryName = Literal["read", "write", "delete", "send", "approve"]
"""An action's permission category (`identity.actions.PermissionCategory`, Story 7.4)."""


class ToolPermissionOption(BaseModel):
    """A tool permission an Agent may be granted, with its action's category (Story 7.4;
    always `read`)."""

    action: str
    category: PermissionCategoryName


class AgentConfigOptions(BaseModel):
    """What a new config version of this Agent may reference, from the deployed manifest
    (Story 7.3): the model profiles, the Agent's deployed prompt versions, its input schema
    versions and its output schema versions written for the deployed contract version, and
    the grantable tool permissions (`read` actions that are ToolGateway tools, Story 7.4).
    Each list is sorted."""

    model_profiles: list[str]
    prompt_versions: list[int]
    input_schema_versions: list[int]
    output_schema_versions: list[int]
    tool_permissions: list[ToolPermissionOption]


class ToolDenial(BaseModel):
    """One denied ToolGateway call (Story 7.4), from `platform_tool_calls`. Ids, codes and
    the time only: never an Opportunity name, a prompt or Source text. `semver` is the
    calling config version's (null if that version is unknown); `run_id` and `task_id` are
    null for a call made outside a run. `threshold_exceeded`: the call's run passed the
    denial alert threshold."""

    id: str
    created_at: datetime
    agent_id: str
    semver: str | None
    config_version_id: str
    tool: str
    reason: Literal["tool_not_permitted", "out_of_scope", "unknown_tool", "not_allowlisted"]
    opportunity_id: str
    run_id: str | None
    task_id: str | None
    threshold_exceeded: bool


class ToolDenialPage(BaseModel):
    """One page of denied tool calls, newest first."""

    items: list[ToolDenial]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


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


# --- evaluation results (Story 7.6) ---------------------------------------------------------

EvalMetric = Literal[
    "extraction_recall",
    "citation_validity",
    "gap_recall",
    "irrelevant_gaps",
    "mandatory_gap_recall",
    "evidence_support",
    "schema_valid_rate",
    "integration_risk_recall",
]
EvalStage = Literal["parse", "extraction", "gap_detection", "specialists", "estimate", "red_team"]


class EvalScores(BaseModel):
    """Metric values in percent (0-100), null when there was nothing to measure: `overall`
    across the reference set, and `per_agent` (agent id → metric → value) for the Agents
    each metric belongs to."""

    overall: dict[str, float | None]
    per_agent: dict[str, dict[str, float | None]]


class EvalBar(BaseModel):
    """One release bar. `comparator` `min`: the value must be at least `threshold`; `max`:
    at most. `delta`: the value minus the last accepted result's, in points (null on the
    first eval or when either is unmeasured). `regressed`: more than 5 points worse than the
    last accepted result, which fails the bar. `not_measured` is a warning, never a fail."""

    metric: EvalMetric
    label: str
    requirement: str
    agent_ids: list[str]
    comparator: Literal["min", "max"]
    threshold: float
    value: float | None
    status: Literal["pass", "fail", "not_measured"]
    delta: float | None
    regressed: bool


class EvalFailure(BaseModel):
    """A pipeline stage that failed for one reference Opportunity: its later metrics score
    0 and the result does not pass. `code`: the stage's error code or job status."""

    slug: str
    stage: EvalStage
    code: str


class EvalCost(BaseModel):
    amount_minor: int = Field(ge=0)
    currency: str


class EvalResult(BaseModel):
    """One stored evaluation result. `accepted`: it passed and is the comparison point for
    later results. `config_version_ids`, `model_digests` (the digests the model calls
    reported) and `prompt_versions` are keyed by agent id."""

    id: str
    reference_set_version: str
    config_version_ids: dict[str, str]
    model_digests: dict[str, list[str]]
    prompt_versions: dict[str, int]
    scores: EvalScores
    bars: list[EvalBar]
    failures: list[EvalFailure]
    opportunity_count: int
    draft_count: int
    pending_count: int
    tokens: int
    gpu_seconds: float
    cost: EvalCost
    passed: bool
    accepted: bool
    created_by: str
    created_at: datetime


class EvalResultList(BaseModel):
    """Evaluation results, newest first."""

    items: list[EvalResult]


class NewEvalResult(BaseModel):
    """What the harness hands `record_eval_result`. The bars, `passed` and `accepted` are
    derived from `scores.overall` and the last accepted result, never taken from the caller."""

    model_config = ConfigDict(extra="forbid")

    reference_set_version: str
    config_version_ids: dict[str, str]
    model_digests: dict[str, list[str]]
    prompt_versions: dict[str, int]
    scores: EvalScores
    failures: list[EvalFailure]
    opportunity_count: int = Field(ge=0)
    draft_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    tokens: int = Field(ge=0)
    gpu_seconds: float = Field(ge=0)
    cost: EvalCost
