"""The Agent Registry's commands and queries (Story 7.1).

Writes follow the AD-3 path: `identity.authorize` (the `registry.*` actions, platform
administrators only; anyone else gets 403), validate, `If-Match` on the Agent (428 without,
412 when stale; registering has no Agent yet), write, then trace with no Opportunity, all in
the caller's Unit of Work.

- `register_agent`: a new Agent (`active`) with its config version 1. A taken agent id is
  409 `registry_agent_duplicate`.
- `create_config_version`: inserts version n+1, which becomes current. Runs already in
  progress keep the version they pinned.
- `set_status`: `active`, `disabled` or `eval_only`; the same status is a 200 no-op.

Every config is checked against the deployed manifest (`app.agents.manifest`): a prompt,
input or output schema, or model profile it doesn't list is 422
`registry_config_not_deployed`; an output schema written for another contract version than
`CONTRACT_VERSION` is 422 `registry_config_incompatible_contract`. Nothing is stored then.

Reads (`read_agents`, `read_agent`, `read_versions`) are for platform administrators too.

Evaluation results (Story 7.6): `record_eval_result` (the eval harness, a system actor; no
authorization) judges the scores against the bars and the last accepted result of the same
reference-set version, inserts the
insert-only row and traces `registry.eval.completed` (no Opportunity) in one Unit of Work.
`read_evals` and `read_eval` are for platform administrators. `install_eval_config` copies a
config version into the eval database as its Agent's newest version (harness only).

For other modules (no authorization): `current_config`, `get_config_version`, `list_agents`,
`require_enabled` (409 `registry_agent_disabled` for a `disabled` or `eval_only` Agent) and
`agent_config` (the `AgentConfig` an agent runs with, applying the local-dev profile
override: when `PSA_MODEL_PROFILE_CHAT` is explicitly set it replaces the version's pinned
profile, and the model call records the profile actually used).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.agents import manifest as deployed
from app.agents.contract import CONTRACT_VERSION, AgentConfig
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Role
from app.modules.registry.adapters import repository as repo
from app.modules.registry.adapters.models import EvalResultRow
from app.modules.registry.application.models import (
    AgentConfigVersion,
    AgentConfigVersionList,
    AgentStatusChange,
    EvalBar,
    EvalCost,
    EvalFailure,
    EvalResult,
    EvalResultList,
    EvalScores,
    NewAgent,
    NewAgentConfig,
    NewEvalResult,
    RegistryAgent,
    RegistryAgentList,
)
from app.modules.registry.domain import evals as gate
from app.modules.registry.domain import registry as rules
from app.modules.registry.domain.registry import (
    AgentStatus,
    ConfigVersion,
    RegisteredAgent,
)
from app.platform import trace
from app.platform.actor import Actor
from app.platform.concurrency import parse_if_match
from app.platform.config import Settings
from app.platform.errors import (
    ForbiddenError,
    NotFoundError,
    RegistryAgentDisabledError,
    RegistryAgentDuplicateError,
    RegistryConfigIncompatibleContractError,
    RegistryConfigNotDeployedError,
    RowVersionMismatchError,
    ToolPermissionNotReadOnlyError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    RegistryAgentConfigVersionCreated,
    RegistryAgentDisabled,
    RegistryAgentEnabled,
    RegistryAgentRegistered,
    RegistryEvalCompleted,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Agent with this id."
EVAL_NOT_FOUND_DETAIL = "No evaluation result with this id."
EVAL_LIST_LIMIT = 100
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_log = get_logger(__name__)


class UnknownAgentError(LookupError):
    """An agent id the registry doesn't hold: a programming or seed error."""


# --- views ---------------------------------------------------------------------------------


def version_view(version: ConfigVersion) -> AgentConfigVersion:
    return AgentConfigVersion(
        id=str(version.id),
        agent_id=version.agent_id,
        version=version.version,
        semver=version.semver,
        model_profile=version.model_profile,
        model_digest=version.model_digest,
        prompt_version=version.prompt_version,
        input_schema_version=version.input_schema_version,
        output_schema_version=version.output_schema_version,
        contract_version=version.contract_version,
        tool_permissions=list(version.tool_permissions),
        budgets=dict(version.budgets),
        created_by_id=None if version.created_by is None else str(version.created_by),
        created_at=version.created_at,
    )


def agent_view(agent: RegisteredAgent) -> RegistryAgent:
    return RegistryAgent(
        id=str(agent.id),
        agent_id=agent.agent_id,
        name=agent.name,
        status=agent.status,
        row_version=agent.row_version,
        created_at=agent.created_at,
        current_config=version_view(agent.current),
    )


# --- helpers -------------------------------------------------------------------------------


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Agent was changed by someone else since you opened it. Reload and try again."
    )


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        raise _stale()
    return expected


def _require_admin(actor: Principal) -> None:
    if Role.PLATFORM_ADMINISTRATOR not in actor.roles:
        raise ForbiddenError("You are not allowed to perform this action.")


def _writer(actor: Principal, action: Action) -> UUID:
    identity.authorize(actor, action)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can change the Agent Registry.")
    return user_id


def _invalid[T, V](value: V, check: Callable[[V], T]) -> T:
    """Run a field rule; a rule's `ValueError` is a 422 whose detail is the sentence to show."""
    try:
        return check(value)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None


async def _load(uow: UnitOfWork, agent_id: str) -> RegisteredAgent:
    agent = await repo.get_agent(uow, agent_id)
    if agent is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return agent


@dataclass(frozen=True, slots=True)
class _CheckedConfig:
    """A config that passed the field rules and the manifest checks."""

    semver: str
    model_profile: str
    prompt_version: int
    input_schema_version: int
    output_schema_version: int
    contract_version: str
    tool_permissions: tuple[str, ...]
    budgets: dict[str, Any]


def check_deployed(agent_id: str, new: NewAgentConfig) -> _CheckedConfig:
    """The field rules, then the manifest: every referenced prompt, schema and profile must
    be deployed, and the output schema written for `CONTRACT_VERSION`."""
    semver = _invalid(new.semver, rules.semver)
    try:
        tool_permissions = rules.tool_permissions(new.tool_permissions)
    except rules.ToolPermissionNotReadOnly as exc:  # only READ tools (Story 5.4)
        raise ToolPermissionNotReadOnlyError(str(exc)) from None
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    budgets = _invalid(new.budgets, rules.budgets)
    profile = new.model_profile.strip()
    manifest = deployed.load()
    missing: list[str] = []
    if not manifest.has_prompt(agent_id, new.prompt_version):
        missing.append(f"prompt v{new.prompt_version}")
    if manifest.schema(agent_id, "input", new.input_schema_version) is None:
        missing.append(f"input schema v{new.input_schema_version}")
    output = manifest.schema(agent_id, "output", new.output_schema_version)
    if output is None:
        missing.append(f"output schema v{new.output_schema_version}")
    if not manifest.has_profile(profile):
        missing.append(f"model profile {profile!r}")
    if missing or output is None:
        raise RegistryConfigNotDeployedError(
            f"Not in the deployed manifest for {agent_id}: {', '.join(missing)}."
        )
    contract = str(output.get("contract_version", ""))
    if contract != CONTRACT_VERSION:
        raise RegistryConfigIncompatibleContractError(
            f"Output schema v{new.output_schema_version} was written for contract version "
            f"{contract!r}; the deployed contract version is {CONTRACT_VERSION!r}."
        )
    return _CheckedConfig(
        semver=semver,
        model_profile=profile,
        prompt_version=new.prompt_version,
        input_schema_version=new.input_schema_version,
        output_schema_version=new.output_schema_version,
        contract_version=contract,
        tool_permissions=tool_permissions,
        budgets=budgets,
    )


async def _insert_version(
    uow: UnitOfWork,
    agent_id: str,
    version: int,
    config: _CheckedConfig,
    user_id: UUID,
) -> UUID:
    config_version_id = new_id()
    await repo.insert_version(
        uow,
        config_version_id=config_version_id,
        agent_id=agent_id,
        version=version,
        semver=config.semver,
        model_profile=config.model_profile,
        model_digest=rules.UNPINNED_DIGEST,
        prompt_version=config.prompt_version,
        input_schema_version=config.input_schema_version,
        output_schema_version=config.output_schema_version,
        contract_version=config.contract_version,
        tool_permissions=config.tool_permissions,
        budgets=config.budgets,
        user_id=user_id,
    )
    return config_version_id


# --- reads (platform administrators) -------------------------------------------------------


async def read_agents(uow: UnitOfWork, actor: Principal) -> RegistryAgentList:
    """Every Agent with its status and current config version, by agent id."""
    _require_admin(actor)
    return RegistryAgentList(items=[agent_view(a) for a in await repo.list_agents(uow)])


async def read_agent(uow: UnitOfWork, actor: Principal, agent_id: str) -> RegistryAgent:
    _require_admin(actor)
    return agent_view(await _load(uow, agent_id))


async def read_versions(uow: UnitOfWork, actor: Principal, agent_id: str) -> AgentConfigVersionList:
    """The Agent's config versions, newest first."""
    _require_admin(actor)
    await _load(uow, agent_id)
    return AgentConfigVersionList(
        items=[version_view(v) for v in await repo.list_versions(uow, agent_id)]
    )


# --- writes (platform administrators) ------------------------------------------------------


async def register_agent(uow: UnitOfWork, actor: Principal, new: NewAgent) -> RegistryAgent:
    """A new `active` Agent with its config version 1."""
    user_id = _writer(actor, Action.REGISTRY_AGENT_REGISTER)
    agent_id = _invalid(new.agent_id, rules.agent_id)
    name = _invalid(new.name, rules.agent_name)
    config = check_deployed(agent_id, new.config)
    await repo.lock_registry(uow)
    if await repo.agent_exists(uow, agent_id):
        raise RegistryAgentDuplicateError(f"An Agent with the id {agent_id} already exists.")
    await repo.insert_agent(
        uow,
        row_id=rules.agent_row_id(agent_id),
        agent_id=agent_id,
        name=name,
        status=AgentStatus.ACTIVE,
        user_id=user_id,
    )
    config_version_id = await _insert_version(uow, agent_id, 1, config, user_id)
    agent = await _load(uow, agent_id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=RegistryAgentRegistered(
            agent_id=agent_id,
            status=AgentStatus.ACTIVE.value,
            to_config_version_id=str(config_version_id),
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=agent.id,
        subject_version=1,
    )
    _log.info(
        "registry.agent_registered",
        extra={
            "agent_id": agent_id,
            "config_version_id": str(config_version_id),
            "actor_id": str(user_id),
        },
    )
    return agent_view(agent)


async def create_config_version(
    uow: UnitOfWork,
    actor: Principal,
    agent_id: str,
    new: NewAgentConfig,
    if_match: str | None,
) -> RegistryAgent:
    """Insert the Agent's next config version, which becomes current. `if_match` is the raw
    `If-Match` header (the Agent's row version)."""
    user_id = _writer(actor, Action.REGISTRY_AGENT_CONFIG_CREATE)
    expected = _expected(if_match)
    agent = await _load(uow, agent_id)
    config = check_deployed(agent.agent_id, new)
    if agent.row_version != expected:
        raise _stale()
    if await repo.bump(uow, agent.agent_id, expected_row_version=expected) is None:
        raise _stale()
    # The bump holds the Agent's row lock until commit, so the number can't be raced.
    before = await _load(uow, agent.agent_id)
    to_version = before.current.version + 1
    config_version_id = await _insert_version(uow, agent.agent_id, to_version, config, user_id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=RegistryAgentConfigVersionCreated(
            agent_id=agent.agent_id,
            version=to_version,
            from_config_version_id=str(before.current.id),
            to_config_version_id=str(config_version_id),
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=agent.id,
        subject_version=to_version,
    )
    _log.info(
        "registry.agent_config_version_created",
        extra={
            "agent_id": agent.agent_id,
            "version": to_version,
            "config_version_id": str(config_version_id),
            "actor_id": str(user_id),
        },
    )
    return agent_view(await _load(uow, agent.agent_id))


async def set_status(
    uow: UnitOfWork,
    actor: Principal,
    agent_id: str,
    change: AgentStatusChange,
    if_match: str | None,
) -> RegistryAgent:
    """Set the Agent `active`, `disabled` or `eval_only`. Only `active` Agents get new tasks;
    tasks already running finish."""
    user_id = _writer(actor, Action.REGISTRY_AGENT_SET_STATUS)
    expected = _expected(if_match)
    agent = await _load(uow, agent_id)
    if agent.row_version != expected:
        raise _stale()
    if agent.status == change.status:
        return agent_view(agent)
    if (
        await repo.bump(uow, agent.agent_id, expected_row_version=expected, status=change.status)
        is None
    ):
        raise _stale()
    current = str(agent.current.id)
    payload: RegistryAgentEnabled | RegistryAgentDisabled
    if change.status == AgentStatus.ACTIVE:
        payload = RegistryAgentEnabled(
            agent_id=agent.agent_id,
            from_status=agent.status.value,
            to_status="active",
            from_config_version_id=current,
            to_config_version_id=current,
        )
    else:
        payload = RegistryAgentDisabled(
            agent_id=agent.agent_id,
            from_status=agent.status.value,
            to_status="disabled" if change.status == AgentStatus.DISABLED else "eval_only",
            from_config_version_id=current,
            to_config_version_id=current,
        )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=payload,
        subject_type=rules.SUBJECT_TYPE,
        subject_id=agent.id,
        subject_version=agent.current.version,
    )
    _log.info(
        "registry.agent_status_set",
        extra={
            "agent_id": agent.agent_id,
            "from_status": agent.status.value,
            "to_status": change.status.value,
            "actor_id": str(user_id),
        },
    )
    return agent_view(await _load(uow, agent.agent_id))


# --- for other modules (no authorization) ---------------------------------------------------


async def current_config(uow: UnitOfWork, agent_id: str) -> RegisteredAgent:
    """The Agent with its status and current config version. Raises `UnknownAgentError` for
    an agent id the registry doesn't hold."""
    agent = await repo.get_agent(uow, agent_id)
    if agent is None:
        raise UnknownAgentError(f"agent {agent_id!r} is not in the Agent Registry")
    return agent


async def require_enabled(uow: UnitOfWork, agent_id: str) -> RegisteredAgent:
    """`current_config`, but a `disabled` or `eval_only` Agent raises 409
    `registry_agent_disabled` ("<Agent> is disabled")."""
    agent = await current_config(uow, agent_id)
    if not agent.runs_tasks:
        raise disabled_error(agent)
    return agent


def disabled_error(agent: RegisteredAgent) -> RegistryAgentDisabledError:
    return RegistryAgentDisabledError(f"{agent.name} is disabled")


async def get_config_version(uow: UnitOfWork, config_version_id: UUID) -> ConfigVersion | None:
    return await repo.get_version(uow, config_version_id)


async def get_config_versions(
    uow: UnitOfWork, config_version_ids: list[UUID]
) -> dict[UUID, ConfigVersion]:
    return await repo.versions_by_id(uow, config_version_ids)


async def list_agents(uow: UnitOfWork) -> list[RegisteredAgent]:
    return await repo.list_agents(uow)


def effective_profile(version: ConfigVersion, settings: Settings) -> str:
    """The profile the agent calls: `PSA_MODEL_PROFILE_CHAT` when it is explicitly set (a
    local-dev override), else the profile the config version pins."""
    if "model_profile_chat" in settings.model_fields_set:
        return settings.model_profile_chat
    return version.model_profile


def agent_config(version: ConfigVersion, settings: Settings) -> AgentConfig:
    """The `AgentConfig` an agent runs with at this config version."""
    return AgentConfig(
        agent_id=version.agent_id,
        semver=version.semver,
        prompt_version=version.prompt_version,
        profile=effective_profile(version, settings),
        config_version_id=version.id,
    )


# --- evaluation results (Story 7.6) ---------------------------------------------------------


def eval_view(row: EvalResultRow) -> EvalResult:
    return EvalResult(
        id=str(row.id),
        reference_set_version=row.reference_set_version,
        config_version_ids=dict(row.config_version_ids),
        model_digests={k: list(v) for k, v in row.model_digests.items()},
        prompt_versions={k: int(v) for k, v in row.prompt_versions.items()},
        scores=EvalScores.model_validate(row.scores),
        bars=[EvalBar.model_validate(bar) for bar in row.bars],
        failures=[EvalFailure.model_validate(f) for f in row.failures],
        opportunity_count=row.opportunity_count,
        draft_count=row.draft_count,
        pending_count=row.pending_count,
        tokens=row.tokens,
        gpu_seconds=row.gpu_seconds,
        cost=EvalCost(amount_minor=row.cost_minor, currency=row.cost_currency),
        passed=row.passed,
        accepted=row.accepted,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def bar_view(result: gate.BarResult) -> EvalBar:
    spec = result.spec
    return EvalBar(
        metric=spec.metric.value,
        label=spec.label,
        requirement=spec.requirement,
        agent_ids=list(spec.agent_ids),
        comparator=spec.comparator,
        threshold=spec.threshold,
        value=result.value,
        status=result.status.value,
        delta=result.delta,
        regressed=result.regressed,
    )


def judge_eval(
    scores: EvalScores, previous: EvalResult | None, *, failure_count: int
) -> tuple[list[EvalBar], bool]:
    """The bars of `scores` against their thresholds and the last accepted result, and
    whether the result passes (see `domain.evals.judge`)."""
    results, passed = gate.judge(
        scores.overall,
        None if previous is None else previous.scores.overall,
        failure_count=failure_count,
    )
    return [bar_view(r) for r in results], passed


async def last_accepted_eval(uow: UnitOfWork, reference_set_version: str) -> EvalResult | None:
    """The newest accepted result of the same reference-set version: the comparison point
    for the next eval of that set (like with like; another version is never compared)."""
    row = await repo.latest_accepted_eval(uow, reference_set_version)
    return None if row is None else eval_view(row)


async def record_eval_result(uow: UnitOfWork, actor: Actor, new: NewEvalResult) -> EvalResult:
    """Judge the result against the bars and the last accepted result, insert it (`accepted`
    when it passed) and trace `registry.eval.completed`, in the caller's Unit of Work."""
    version = _invalid(new.reference_set_version, gate.reference_set_version)
    currency = new.cost.currency.strip().upper()
    if not _CURRENCY_RE.match(currency):
        raise UnprocessableError("The cost currency must be an ISO-4217 code, e.g. `EUR`.")
    previous = await last_accepted_eval(uow, version)
    bars, passed = judge_eval(new.scores, previous, failure_count=len(new.failures))
    result_id = new_id()
    await repo.insert_eval_result(
        uow,
        {
            "id": result_id,
            "reference_set_version": version,
            "config_version_ids": dict(new.config_version_ids),
            "model_digests": {k: list(v) for k, v in new.model_digests.items()},
            "prompt_versions": dict(new.prompt_versions),
            "scores": new.scores.model_dump(mode="json"),
            "bars": [bar.model_dump(mode="json") for bar in bars],
            "failures": [f.model_dump(mode="json") for f in new.failures],
            "opportunity_count": new.opportunity_count,
            "draft_count": new.draft_count,
            "pending_count": new.pending_count,
            "tokens": new.tokens,
            "gpu_seconds": new.gpu_seconds,
            "cost_minor": new.cost.amount_minor,
            "cost_currency": currency,
            "passed": passed,
            "accepted": passed,
            "created_by": actor.id,
        },
    )
    await trace.append(
        uow,
        actor=actor,
        payload=RegistryEvalCompleted(
            result_id=str(result_id),
            reference_set_version=version,
            config_version_ids=dict(new.config_version_ids),
            opportunity_count=new.opportunity_count,
            failed_bar_count=sum(1 for b in bars if b.status == "fail"),
            not_measured_bar_count=sum(1 for b in bars if b.status == "not_measured"),
            pending_count=new.pending_count,
            failure_count=len(new.failures),
            passed=passed,
            accepted=passed,
        ),
        subject_type=gate.SUBJECT_TYPE,
        subject_id=result_id,
    )
    _log.info(
        "registry.eval_completed",
        extra={"result_id": str(result_id), "passed": passed, "actor_id": actor.id},
    )
    row = await repo.get_eval_result(uow, result_id)
    if row is None:  # pragma: no cover - inserted just above in this transaction
        raise NotFoundError(EVAL_NOT_FOUND_DETAIL)
    return eval_view(row)


async def read_evals(uow: UnitOfWork, actor: Principal) -> EvalResultList:
    """The newest evaluation results (at most 100), newest first."""
    _require_admin(actor)
    rows = await repo.list_eval_results(uow, EVAL_LIST_LIMIT)
    return EvalResultList(items=[eval_view(row) for row in rows])


async def read_eval(uow: UnitOfWork, actor: Principal, result_id: UUID) -> EvalResult:
    _require_admin(actor)
    row = await repo.get_eval_result(uow, result_id)
    if row is None:
        raise NotFoundError(EVAL_NOT_FOUND_DETAIL)
    return eval_view(row)


async def install_eval_config(
    uow: UnitOfWork, agent: RegisteredAgent, version: ConfigVersion
) -> None:
    """Eval harness only, in the eval database: make `version` (read from the main database)
    the Agent's newest config version there, so the job chain picks it up. Registers the
    Agent when the eval database lacks it, keeps the version's id, and sets the Agent
    `active` unless it is `disabled` (an `eval_only` Agent runs in evals)."""
    status = AgentStatus.DISABLED if agent.status == AgentStatus.DISABLED else AgentStatus.ACTIVE
    if not await repo.agent_exists(uow, agent.agent_id):
        await repo.insert_agent(
            uow,
            row_id=agent.id,
            agent_id=agent.agent_id,
            name=agent.name,
            status=status,
            user_id=None,
        )
    else:
        current = await repo.get_agent(uow, agent.agent_id)
        if current is not None and current.status != status:
            await repo.bump(
                uow, agent.agent_id, expected_row_version=current.row_version, status=status
            )
    newest = await repo.get_agent(uow, agent.agent_id)
    if newest is not None and newest.current.id == version.id:
        return
    if await repo.version_exists(uow, version.id):
        raise UnprocessableError(
            f"Config version {version.id} of {agent.agent_id} is already in the eval database "
            "but not its newest; reset the eval database first."
        )
    await repo.insert_version(
        uow,
        config_version_id=version.id,
        agent_id=agent.agent_id,
        version=await repo.max_version(uow, agent.agent_id) + 1,
        semver=version.semver,
        model_profile=version.model_profile,
        model_digest=version.model_digest,
        prompt_version=version.prompt_version,
        input_schema_version=version.input_schema_version,
        output_schema_version=version.output_schema_version,
        contract_version=version.contract_version,
        tool_permissions=version.tool_permissions,
        budgets=version.budgets,
        user_id=version.created_by,
    )


async def config_versions_of(uow: UnitOfWork, agent_id: str) -> list[ConfigVersion]:
    """The Agent's config versions, newest first (no authorization; the eval harness)."""
    return await repo.list_versions(uow, agent_id)
