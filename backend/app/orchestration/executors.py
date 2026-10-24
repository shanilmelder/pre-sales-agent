"""How a node executes a task, per Agent (AD-5; Story 5.2).

A `TaskExecutor` has three steps, which the node wrapper (`graph.py`) calls in order:

1. `prepare(uow, task)`: load the task's inputs (inside the node's short Unit of Work that
   also marked the task `running`); the specialists read theirs through the ToolGateway as
   the task's Agent, which checks and records every read (Story 5.4).
2. `run(prepared)`: call the Agent, with no Unit of Work open (AD-25). Returns None when
   there is nothing to submit (e.g. no active Requirements: no model call).
3. `accept(uow, task, prepared, result)`: submit the result to its owner's `accept_*`,
   inside the Unit of Work that locked the task as still `running` and then marks it done.

The specialist Agents' executors and (Story 6.4) the Critic's are registered here; tests swap
in fixture ones. The Critic's executor reads its inputs through `assessments`' public query
(the ToolGateway is not wired into its call yet).
"""

from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agents.contract import AgentConfig, AgentResult
from app.agents.critic_agent.agent import CriticAgent
from app.agents.engineering_agent.agent import EngineeringAgent
from app.agents.pm_agent.agent import PmAgent
from app.agents.security_agent.agent import SecurityAgent
from app.agents.specialist.agent import GapBlock, RequirementBlock, SpecialistAgent, SpecialistTask
from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import (
    CRITIC_AGENT,
    AssessmentAgent,
    AssessmentInputs,
    CriticInputs,
)
from app.modules.registry.application import public as registry
from app.modules.workflows.application.public import NodeTask
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelGatewayPort
from app.platform.tool_gateway import ToolContext, ToolGateway, ToolOutcome, ToolResult
from app.platform.tool_gateway.catalogue import GAP_LIST, REQUIREMENT_LIST
from app.platform.uow import UnitOfWork


class TaskExecutor(Protocol):
    async def prepare(self, uow: UnitOfWork, task: NodeTask) -> Any: ...

    async def run(self, prepared: Any) -> Any | None: ...

    async def accept(self, uow: UnitOfWork, task: NodeTask, prepared: Any, result: Any) -> None: ...


def executor_settings() -> Settings:
    """Settings for the specialist executors (the chat profile). Tests replace this."""
    return get_settings()


def _items(outcome: ToolOutcome) -> Sequence[Any]:
    """A read's records; none when it was denied."""
    return outcome.items if isinstance(outcome, ToolResult) else ()


@dataclass(frozen=True, slots=True)
class SpecialistPrepared:
    task: NodeTask
    inputs: AssessmentInputs = field(repr=False)
    config: AgentConfig


@dataclass(frozen=True, slots=True)
class SpecialistExecutor:
    """A specialist Agent's task: the Opportunity's active Requirements and open Gaps in,
    an Assessment out (`assessments.accept_assessment`)."""

    agent: AssessmentAgent
    build: Callable[[ModelGatewayPort, AgentConfig], SpecialistAgent]

    async def prepare(self, uow: UnitOfWork, task: NodeTask) -> SpecialistPrepared:
        """Read the Requirements and open Gaps through the ToolGateway as the task's Agent at
        its pinned config version (Story 5.4), in the node's Unit of Work. A denied read
        reads nothing: no Requirements means no model call; no Gaps, a prompt without."""
        versions = await registry.get_config_versions(uow, [task.config_version_id])
        version = versions[task.config_version_id]
        settings = executor_settings()
        config = registry.agent_config(version, settings)
        context = ToolContext(
            agent_id=version.agent_id,
            semver=version.semver,
            config_version_id=version.id,
            tool_permissions=frozenset(version.tool_permissions),
            opportunity_id=task.opportunity_id,
            run_id=task.run_id,
            task_id=task.id,
        )
        tools = ToolGateway(settings)
        requirements = await tools.call(context, REQUIREMENT_LIST, uow=uow)
        open_gaps = await tools.call(context, GAP_LIST, uow=uow)
        inputs = assessments.build_inputs(_items(requirements), _items(open_gaps))
        return SpecialistPrepared(task=task, inputs=inputs, config=config)

    async def run(self, prepared: SpecialistPrepared) -> AgentResult | None:
        if not prepared.inputs.requirements:  # nothing to assess: no model call
            return None
        specialist = self.build(provider.current(), prepared.config)
        return await specialist.run(
            SpecialistTask(
                opportunity_id=prepared.task.opportunity_id,
                run_id=prepared.task.run_id,
                requirements=[
                    RequirementBlock(r.label, r.classification, r.text)
                    for r in prepared.inputs.requirements
                ],
                gaps=[
                    GapBlock(
                        label=g.label,
                        category=g.category,
                        impact=g.impact,
                        title=g.title,
                        why_it_matters=g.why_it_matters,
                    )
                    for g in prepared.inputs.gaps
                ],
            )
        )

    async def accept(
        self, uow: UnitOfWork, task: NodeTask, prepared: SpecialistPrepared, result: AgentResult
    ) -> None:
        await assessments.accept_assessment(
            uow,
            opportunity_id=task.opportunity_id,
            run_id=task.run_id,
            agent=self.agent,
            config_version_id=task.config_version_id,
            result=result,
            inputs=prepared.inputs,
            actor=Actor(type="agent", id=prepared.config.actor_id),
        )


@dataclass(frozen=True, slots=True)
class CriticPrepared:
    task: NodeTask
    inputs: CriticInputs = field(repr=False)
    config: AgentConfig


@dataclass(frozen=True, slots=True)
class CriticExecutor:
    """The Critic's task (Story 6.4): the Assessments the run accepted in, a Critic Review
    out (`assessments.accept_critic_review`). With no Assessment accepted in the run there
    is nothing to review: no model call, no Review, and the task succeeds."""

    build: Callable[[ModelGatewayPort, AgentConfig], CriticAgent] = lambda gateway, config: (
        CriticAgent(gateway, config=config)
    )

    async def prepare(self, uow: UnitOfWork, task: NodeTask) -> CriticPrepared:
        """Read the run's Assessments, the active Requirements and the uncovered ones, in the
        node's Unit of Work, with the task's pinned config version."""
        versions = await registry.get_config_versions(uow, [task.config_version_id])
        config = registry.agent_config(versions[task.config_version_id], executor_settings())
        inputs = await assessments.load_critic_inputs(uow, task.opportunity_id, task.run_id)
        return CriticPrepared(task=task, inputs=inputs, config=config)

    async def run(self, prepared: CriticPrepared) -> AgentResult | None:
        inputs = prepared.inputs
        if not inputs.assessment_count:  # no Assessment accepted in the run: no model call
            return None
        critic = self.build(provider.current(), prepared.config)
        return await critic.run(
            assessments.critic_task(
                inputs, opportunity_id=prepared.task.opportunity_id, run_id=prepared.task.run_id
            )
        )

    async def accept(
        self, uow: UnitOfWork, task: NodeTask, prepared: CriticPrepared, result: AgentResult
    ) -> None:
        await assessments.accept_critic_review(
            uow,
            opportunity_id=task.opportunity_id,
            run_id=task.run_id,
            result=result,
            inputs=prepared.inputs,
            actor=Actor(type="agent", id=prepared.config.actor_id),
        )


EXECUTORS: MutableMapping[str, TaskExecutor] = {
    AssessmentAgent.ENGINEERING.value: SpecialistExecutor(
        AssessmentAgent.ENGINEERING,
        lambda gateway, config: EngineeringAgent(gateway, config=config),
    ),
    AssessmentAgent.PM.value: SpecialistExecutor(
        AssessmentAgent.PM, lambda gateway, config: PmAgent(gateway, config=config)
    ),
    AssessmentAgent.SECURITY.value: SpecialistExecutor(
        AssessmentAgent.SECURITY, lambda gateway, config: SecurityAgent(gateway, config=config)
    ),
    CRITIC_AGENT: CriticExecutor(),
}
"""The executor of each Agent id a plan may contain."""


class NoExecutorError(LookupError):
    """A task's Agent has no executor in this process (a programming error)."""


def executor_for(agent: str) -> TaskExecutor:
    try:
        return EXECUTORS[agent]
    except KeyError:
        raise NoExecutorError(f"no executor for agent {agent!r}") from None
