"""Persistence for the Agent Registry (Story 7.1) and its evaluation results (Story 7.6). Runs
inside the caller's Unit of Work."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.sql.expression import ScalarSelect

from app.modules.registry.adapters.models import AgentRow, ConfigVersionRow, EvalResultRow
from app.modules.registry.domain.registry import AgentStatus, ConfigVersion, RegisteredAgent
from app.platform.uow import UnitOfWork

A = AgentRow
V = ConfigVersionRow
E = EvalResultRow


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
