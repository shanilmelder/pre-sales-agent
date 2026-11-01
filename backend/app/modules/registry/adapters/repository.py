"""Persistence for the Agent Registry (Story 7.1), its evaluation results (Story 7.6), custom
chat model profiles and the approved-model allowlist. Runs inside the caller's Unit of Work."""

from collections.abc import Collection, Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.expression import ScalarSelect

from app.modules.registry.adapters.models import (
    AgentRow,
    ApprovedModelRow,
    ConfigVersionRow,
    EvalResultRow,
    ModelProfileRow,
)
from app.modules.registry.domain.model_profiles import (
    ApprovedModel,
    CustomProfile,
    CustomProvider,
    ProfileState,
)
from app.modules.registry.domain.registry import AgentStatus, ConfigVersion, RegisteredAgent
from app.platform.uow import UnitOfWork

A = AgentRow
V = ConfigVersionRow
E = EvalResultRow
P = ModelProfileRow
M = ApprovedModelRow


async def lock_registry(uow: UnitOfWork) -> None:
    """Serialise registering Agents until commit, so the duplicate check and the insert that
    follows it can't interleave with another."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "registry.agents"},
    )


def _current_version() -> ScalarSelect[int]:
    return (
        select(func.max(V.version)).where(V.agent_id == A.agent_id).correlate(A).scalar_subquery()
    )


def config_version(row: V) -> ConfigVersion:
    return ConfigVersion(
        id=row.id,
        agent_id=row.agent_id,
        version=row.version,
        semver=row.semver,
        model_profile=row.model_profile,
        model_digest=row.model_digest,
        prompt_version=row.prompt_version,
        input_schema_version=row.input_schema_version,
        output_schema_version=row.output_schema_version,
        contract_version=row.contract_version,
        tool_permissions=tuple(row.tool_permissions),
        budgets=dict(row.budgets),
        created_by=row.created_by,
        created_at=row.created_at,
        reason=row.reason,
        restored_from_version=row.restored_from_version,
    )


def _agent(agent: A, version: V) -> RegisteredAgent:
    return RegisteredAgent(
        id=agent.id,
        agent_id=agent.agent_id,
        name=agent.name,
        status=AgentStatus(agent.status),
        row_version=agent.row_version,
        created_at=agent.created_at,
        current=config_version(version),
    )


async def list_agents(uow: UnitOfWork) -> list[RegisteredAgent]:
    """Every Agent with its current config version, by agent id."""
    statement = (
        select(A, V)
        .join(V, (V.agent_id == A.agent_id) & (V.version == _current_version()))
        .order_by(A.agent_id)
        .execution_options(populate_existing=True)
    )
    rows = (await uow.session.execute(statement)).all()
    return [_agent(agent, version) for agent, version in rows]


async def get_agent(
    uow: UnitOfWork, agent_id: str, *, for_update: bool = False
) -> RegisteredAgent | None:
    statement = (
        select(A, V)
        .join(V, (V.agent_id == A.agent_id) & (V.version == _current_version()))
        .where(A.agent_id == agent_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update(of=A)
    row = (await uow.session.execute(statement)).first()
    return None if row is None else _agent(row[0], row[1])


async def agent_exists(uow: UnitOfWork, agent_id: str) -> bool:
    found = await uow.session.execute(select(A.id).where(A.agent_id == agent_id))
    return found.first() is not None


async def get_version(uow: UnitOfWork, config_version_id: UUID) -> ConfigVersion | None:
    row = (
        await uow.session.execute(select(V).where(V.id == config_version_id))
    ).scalar_one_or_none()
    return None if row is None else config_version(row)


async def versions_by_id(
    uow: UnitOfWork, config_version_ids: Sequence[UUID]
) -> dict[UUID, ConfigVersion]:
    if not config_version_ids:
        return {}
    rows = await uow.session.execute(select(V).where(V.id.in_(list(config_version_ids))))
    return {row.id: config_version(row) for row in rows.scalars()}


async def list_versions(uow: UnitOfWork, agent_id: str) -> list[ConfigVersion]:
    """The Agent's config versions, newest first."""
    rows = await uow.session.execute(
        select(V).where(V.agent_id == agent_id).order_by(V.version.desc())
    )
    return [config_version(row) for row in rows.scalars()]


async def insert_agent(
    uow: UnitOfWork,
    *,
    row_id: UUID,
    agent_id: str,
    name: str,
    status: AgentStatus,
    user_id: UUID | None,
) -> None:
    await uow.session.execute(
        insert(A).values(
            id=row_id,
            agent_id=agent_id,
            name=name,
            status=status.value,
            created_by=user_id,
            row_version=1,
        )
    )


async def insert_version(
    uow: UnitOfWork,
    *,
    config_version_id: UUID,
    agent_id: str,
    version: int,
    semver: str,
    model_profile: str,
    model_digest: str,
    prompt_version: int,
    input_schema_version: int,
    output_schema_version: int,
    contract_version: str,
    tool_permissions: Sequence[str],
    budgets: Mapping[str, Any],
    user_id: UUID | None,
    reason: str | None = None,
    restored_from_version: int | None = None,
) -> None:
    await uow.session.execute(
        insert(V).values(
            id=config_version_id,
            agent_id=agent_id,
            version=version,
            semver=semver,
            model_profile=model_profile,
            model_digest=model_digest,
            prompt_version=prompt_version,
            input_schema_version=input_schema_version,
            output_schema_version=output_schema_version,
            contract_version=contract_version,
            tool_permissions=list(tool_permissions),
            budgets=dict(budgets),
            reason=reason,
            restored_from_version=restored_from_version,
            created_by=user_id,
        )
    )


async def bump(
    uow: UnitOfWork,
    agent_id: str,
    *,
    expected_row_version: int,
    status: AgentStatus | None = None,
) -> int | None:
    """Bump the Agent's row version if it is still at `expected_row_version`, optionally
    setting its status; the new row version, or None (no change) when stale."""
    values: dict[str, object] = {"row_version": A.row_version + 1}
    if status is not None:
        values["status"] = status.value
    row = (
        await uow.session.execute(
            update(A)
            .where(A.agent_id == agent_id, A.row_version == expected_row_version)
            .values(**values)
            .returning(A.row_version)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if row is None else row[0]


async def get_version_number(uow: UnitOfWork, agent_id: str, version: int) -> ConfigVersion | None:
    """The Agent's config version with this number, if any."""
    row = (
        await uow.session.execute(select(V).where(V.agent_id == agent_id, V.version == version))
    ).scalar_one_or_none()
    return None if row is None else config_version(row)


async def max_version(uow: UnitOfWork, agent_id: str) -> int:
    """The Agent's highest config version number, 0 when it has none."""
    found = await uow.session.execute(select(func.max(V.version)).where(V.agent_id == agent_id))
    return int(found.scalar_one() or 0)


async def version_exists(uow: UnitOfWork, config_version_id: UUID) -> bool:
    found = await uow.session.execute(select(V.id).where(V.id == config_version_id))
    return found.first() is not None


# --- evaluation results (Story 7.6) ---------------------------------------------------------


async def insert_eval_result(uow: UnitOfWork, values: Mapping[str, Any]) -> None:
    await uow.session.execute(insert(E).values(**values))


async def get_eval_result(uow: UnitOfWork, result_id: UUID) -> EvalResultRow | None:
    found = await uow.session.execute(select(E).where(E.id == result_id))
    return found.scalar_one_or_none()


async def list_eval_results(uow: UnitOfWork, limit: int) -> list[EvalResultRow]:
    """The newest `limit` results, newest first."""
    rows = await uow.session.execute(
        select(E).order_by(E.created_at.desc(), E.id.desc()).limit(limit)
    )
    return list(rows.scalars())


async def latest_accepted_eval(uow: UnitOfWork, reference_set_version: str) -> EvalResultRow | None:
    """The newest accepted result of this reference-set version."""
    rows = await uow.session.execute(
        select(E)
        .where(E.accepted.is_(True), E.reference_set_version == reference_set_version)
        .order_by(E.created_at.desc(), E.id.desc())
        .limit(1)
    )
    return rows.scalar_one_or_none()


# --- custom chat model profiles and the approved-model allowlist ----------------------------


async def lock_model_profiles(uow: UnitOfWork) -> None:
    """Serialise creating profiles until commit, so the duplicate check and the insert that
    follows it can't interleave with another."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "registry.model_profiles"},
    )


def custom_profile(row: P) -> CustomProfile:
    return CustomProfile(
        id=row.id,
        name=row.name,
        provider=cast("CustomProvider", row.provider),
        model=row.model,
        num_ctx=row.num_ctx,
        temperature=row.temperature,
        reasoning_effort=row.reasoning_effort,
        state=ProfileState(row.state),
        error_code=row.error_code,
        latency_ms=row.latency_ms,
        tested_at=row.tested_at,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _approved_model(row: M) -> ApprovedModel:
    return ApprovedModel(
        id=row.id,
        provider=cast("CustomProvider", row.provider),
        model=row.model,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def list_model_profiles(uow: UnitOfWork) -> list[CustomProfile]:
    """Every custom profile, newest first."""
    rows = await uow.session.execute(
        select(P)
        .order_by(P.created_at.desc(), P.id.desc())
        .execution_options(populate_existing=True)
    )
    return [custom_profile(row) for row in rows.scalars()]


async def get_model_profile(
    uow: UnitOfWork, profile_id: UUID, *, for_update: bool = False
) -> CustomProfile | None:
    statement = select(P).where(P.id == profile_id).execution_options(populate_existing=True)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else custom_profile(row)


async def model_profile_named(
    uow: UnitOfWork, name: str, *, for_share: bool = False
) -> CustomProfile | None:
    """The profile called `name`. `for_share` holds it until commit, so it can't be retired
    while a new config version pins it."""
    statement = select(P).where(P.name == name).execution_options(populate_existing=True)
    if for_share:
        statement = statement.with_for_update(read=True)
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else custom_profile(row)


async def verified_profile_names(uow: UnitOfWork) -> list[str]:
    rows = await uow.session.execute(
        select(P.name).where(P.state == ProfileState.VERIFIED.value).order_by(P.name)
    )
    return list(rows.scalars())


async def models_of_profiles(uow: UnitOfWork, names: Collection[str]) -> dict[str, str]:
    """The model each of these custom profile names calls."""
    if not names:
        return {}
    rows = await uow.session.execute(select(P.name, P.model).where(P.name.in_(list(names))))
    return {name: model for name, model in rows.tuples()}


async def custom_profiles_named(uow: UnitOfWork, names: Collection[str]) -> list[CustomProfile]:
    if not names:
        return []
    rows = await uow.session.execute(select(P).where(P.name.in_(list(names))))
    return [custom_profile(row) for row in rows.scalars()]


async def insert_model_profile(
    uow: UnitOfWork,
    *,
    profile_id: UUID,
    name: str,
    provider: str,
    model: str,
    num_ctx: int,
    temperature: float | None,
    reasoning_effort: str | None,
    user_id: UUID | None,
) -> None:
    await uow.session.execute(
        insert(P).values(
            id=profile_id,
            name=name,
            provider=provider,
            model=model,
            num_ctx=num_ctx,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            state=ProfileState.UNTESTED.value,
            created_by=user_id,
        )
    )


async def install_model_profile(uow: UnitOfWork, profile: CustomProfile) -> None:
    """Copy a stored profile into another database (the eval harness), keeping its state."""
    await uow.session.execute(
        pg_insert(P)
        .values(
            id=profile.id,
            name=profile.name,
            provider=profile.provider,
            model=profile.model,
            num_ctx=profile.num_ctx,
            temperature=profile.temperature,
            reasoning_effort=profile.reasoning_effort,
            state=profile.state.value,
            error_code=profile.error_code,
            latency_ms=profile.latency_ms,
            tested_at=profile.tested_at,
            created_by=profile.created_by,
            created_at=profile.created_at,
        )
        .on_conflict_do_nothing()
    )


async def record_model_profile_test(
    uow: UnitOfWork,
    profile_id: UUID,
    *,
    state: ProfileState,
    error_code: str | None,
    latency_ms: int,
) -> bool:
    """Finish an `untested` profile's test; False (no change) in any other state."""
    done = await uow.session.execute(
        update(P)
        .where(P.id == profile_id, P.state == ProfileState.UNTESTED.value)
        .values(
            state=state.value, error_code=error_code, latency_ms=latency_ms, tested_at=func.now()
        )
        .returning(P.id)
        .execution_options(synchronize_session=False)
    )
    return done.first() is not None


async def reset_model_profile_test(uow: UnitOfWork, profile_id: UUID) -> bool:
    """A `failed` or stuck `untested` profile back to a clean `untested`; False (no change) in
    any other state."""
    done = await uow.session.execute(
        update(P)
        .where(
            P.id == profile_id,
            P.state.in_((ProfileState.FAILED.value, ProfileState.UNTESTED.value)),
        )
        .values(state=ProfileState.UNTESTED.value, error_code=None, latency_ms=None, tested_at=None)
        .returning(P.id)
        .execution_options(synchronize_session=False)
    )
    return done.first() is not None


async def retire_model_profile(uow: UnitOfWork, profile_id: UUID) -> None:
    await uow.session.execute(
        update(P)
        .where(P.id == profile_id)
        .values(state=ProfileState.RETIRED.value)
        .execution_options(synchronize_session=False)
    )


async def profile_is_current(uow: UnitOfWork, name: str) -> bool:
    """Whether any Agent's current config version pins this profile."""
    found = await uow.session.execute(
        select(A.id)
        .join(V, (V.agent_id == A.agent_id) & (V.version == _current_version()))
        .where(V.model_profile == name)
        .limit(1)
    )
    return found.first() is not None


async def list_approved_models(uow: UnitOfWork) -> list[ApprovedModel]:
    """The allowlist, by provider and model."""
    rows = await uow.session.execute(select(M).order_by(M.provider, M.model))
    return [_approved_model(row) for row in rows.scalars()]


async def is_approved(uow: UnitOfWork, provider: str, model: str) -> bool:
    found = await uow.session.execute(select(M.id).where(M.provider == provider, M.model == model))
    return found.first() is not None


async def insert_approved_model(
    uow: UnitOfWork, *, approved_id: UUID, provider: str, model: str, user_id: UUID
) -> ApprovedModel | None:
    """The new entry, or None when the pair is already on the allowlist."""
    row = (
        await uow.session.execute(
            pg_insert(M)
            .values(id=approved_id, provider=provider, model=model, created_by=user_id)
            .on_conflict_do_nothing()
            .returning(M)
        )
    ).scalar_one_or_none()
    return None if row is None else _approved_model(row)


async def delete_approved_model(uow: UnitOfWork, approved_id: UUID) -> ApprovedModel | None:
    """Remove the entry and return it, or None when there is no such entry."""
    row = (
        await uow.session.execute(
            delete(M)
            .where(M.id == approved_id)
            .returning(M)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    return None if row is None else _approved_model(row)
