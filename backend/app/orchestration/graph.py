"""A Workflow Run's graph (AD-5, AD-6; Story 5.2): one node per task, built from the run's
plan. A task that waits for none starts from START; one that does (the tasks it `requires`,
and, Story 6.4, those it runs `after`: the Critic's waits for every specialist's) waits for
all of them (a waiting edge), so independent tasks run in the same superstep, concurrently.

The checkpointed state is a cache of control data: the run id and the ids of the tasks a
node finished. Every node re-reads its task from `workflows` before doing anything:

1. Its task no longer queued or running, or its run no longer in progress (cancelled,
   failed as lost, or already done, e.g. accepted but not yet checkpointed before a crash):
   the node does nothing.
2. A task it requires ended without succeeding: the task is skipped. One it requires or runs
   after still in progress (it failed on an earlier attempt and runs again): the node does
   nothing this time.
3. A queued task whose Agent is not active (Story 5.5): `workflows.escalation` records a
   `plan_escalation` decision (idempotently, committed first), and the node calls
   LangGraph's `interrupt()` with its payload (ids and codes), outside every `try` (a
   `GraphInterrupt` is an `Exception`). The run then waits for a person. On resume the node
   runs again from its start and the decision row decides: **Continue without** skips the
   task (`agent_disabled`), **Re-plan** runs it (step 4), still open interrupts again.
4. Otherwise: one Unit of Work marks the task `running` and loads its inputs; the Agent is
   called with none open; one Unit of Work locks the task as still `running` (else the
   result is discarded: a cancel came first), submits the result to its owner's `accept_*`
   and marks the task `succeeded`.

A node never raises (LangGraph would cancel its siblings mid-call): an error is reported to
the runner, and on the job's final attempt the task is marked `failed` with its code;
before that it stays `running`, and the job's next attempt re-runs only unfinished tasks.
Logs carry ids and codes only.
"""

import operator
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.workflows.application import public as workflows
from app.modules.workflows.application.public import (
    DecisionChoice,
    DecisionStatus,
    Escalation,
    GraphRun,
    NodeTask,
)
from app.orchestration.executors import TaskExecutor, executor_for
from app.platform.logging import get_logger
from app.platform.uow import unit_of_work

_log = get_logger(__name__)


class RunState(TypedDict, total=False):
    """Checkpointed control data: ids only (AD-6)."""

    run_id: str
    finished: Annotated[list[str], operator.add]
    """Ids of the tasks a node finished (succeeded, failed or skipped), in order."""


@dataclass(slots=True)
class Invocation:
    """One graph invocation's runtime context (never checkpointed): the run and job attempt,
    and the errors its nodes reported."""

    run: GraphRun
    errors: list[BaseException] = field(default_factory=list)


async def submit(
    engine: AsyncEngine,
    task_id: UUID,
    executor: TaskExecutor,
    prepared: Any,
    result: Any | None,
) -> bool:
    """Step 3 of a node, in one Unit of Work: lock the task as still `running`, submit the
    result (None: nothing to submit) and mark the task `succeeded`. False, writing nothing,
    when the task is no longer `running`. An `accept_*` rejection raises and writes nothing."""
    async with unit_of_work(engine) as uow:
        locked = await workflows.lock_running_task(uow, task_id)
        if locked is None:
            return False
        if result is not None:
            await executor.accept(uow, locked, prepared, result)
        await workflows.complete_task(uow, task_id)
    return True


async def _record_failure(invocation: Invocation, task: NodeTask, exc: Exception) -> None:
    code = workflows.error_code(exc)
    ids = {"run_id": str(task.run_id), "task_id": str(task.id), "agent": task.agent}
    invocation.errors.append(exc)
    if not invocation.run.final_attempt:
        _log.warning(
            "orchestration.task_retrying",
            extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
        )
        return
    try:
        async with unit_of_work(invocation.run.engine) as uow:
            await workflows.fail_task(uow, task.id, code.value)
    except Exception as mark_exc:  # e.g. the database is down: the handler fails it later
        _log.warning(
            "orchestration.task_fail_unrecorded",
            extra={**ids, "exc_type": type(mark_exc).__name__},
        )
        return
    _log.info("orchestration.task_failed", extra={**ids, "error_code": code.value})


async def run_task(invocation: Invocation, task_id: UUID) -> RunState:
    """The node wrapper (see the module docstring). Returns the state update."""
    engine = invocation.run.engine
    ids = {"run_id": str(invocation.run.run_id), "task_id": str(task_id)}
    _log.info("orchestration.node_entered", extra=ids)
    ask: Escalation | None = None
    try:
        async with unit_of_work(engine) as uow:
            current = await workflows.node_task(uow, task_id)
            if current is None or not current.pending:
                _log.info("orchestration.node_skipped", extra=ids)
                return {}
            if current.readiness == "blocked":
                skipped = await workflows.skip_blocked_task(uow, task_id)
                _log.info("orchestration.task_blocked", extra={**ids, "skipped": skipped})
                return {"finished": [str(task_id)]} if skipped else {}
            if current.readiness == "waiting":
                _log.info("orchestration.task_waiting", extra=ids)
                return {}
            decided = await workflows.escalation(uow, task_id)
            if decided is not None and decided.open:
                ask = decided  # committed when the Unit of Work closes, before interrupting
            elif decided is not None and decided.choice == DecisionChoice.CONTINUE_WITHOUT:
                skipped = await workflows.skip_disabled_task(uow, task_id)
                _log.info("orchestration.task_continued_without", extra={**ids, "skipped": skipped})
                return {"finished": [str(task_id)]} if skipped else {}
            elif decided is not None and decided.status == DecisionStatus.CANCELLED:
                return {}  # its run was cancelled or ended
            if ask is None:
                executor = executor_for(current.agent)
                started = await workflows.begin_task(uow, task_id)
                if started is None:
                    return {}
                prepared = await executor.prepare(uow, started)
    except Exception as exc:  # e.g. the database: the task stays pending for the handler
        invocation.errors.append(exc)
        _log.warning(
            "orchestration.node_start_failed", extra={**ids, "exc_type": type(exc).__name__}
        )
        return {}
    if ask is not None:
        _log.info(
            "orchestration.task_escalated", extra={**ids, "decision_id": str(ask.decision_id)}
        )
        # Outside every `try`: the GraphInterrupt must reach LangGraph. On resume the node
        # starts again from the top, where the decision row decides.
        interrupt(ask.payload)
        return await run_task(invocation, task_id)
    assert started is not None  # set whenever no decision was asked
    try:
        result = await executor.run(prepared)
        if not await submit(engine, task_id, executor, prepared, result):
            _log.info("orchestration.result_discarded", extra=ids)
            return {}
    except Exception as exc:
        await _record_failure(invocation, started, exc)
        return {"finished": [str(task_id)]} if invocation.run.final_attempt else {}
    _log.info("orchestration.task_succeeded", extra={**ids, "agent": started.agent})
    return {"finished": [str(task_id)]}


def node_name(task_id: UUID) -> str:
    return f"task_{task_id.hex}"


def _node(
    invocation: Invocation, task_id: UUID
) -> Callable[[RunState], Coroutine[Any, Any, RunState]]:
    async def node(state: RunState) -> RunState:
        return await run_task(invocation, task_id)

    return node


def build_graph(
    plan: Sequence[tuple[UUID, tuple[UUID, ...]]],
    invocation: Invocation,
    checkpointer: BaseCheckpointSaver[Any] | None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The run's graph from its plan (each task's id and the ids it waits for). An id that
    is not a task of the plan is ignored."""
    tasks = {task_id for task_id, _ in plan}
    builder: StateGraph[Any, Any, Any, Any] = StateGraph(RunState)
    required: set[UUID] = set()
    for task_id, _ in plan:  # every node first: an edge may name any of them
        # mypy cannot match a TypedDict state to langgraph's TypedDict-like protocols.
        builder.add_node(node_name(task_id), _node(invocation, task_id))  # type: ignore[call-overload]
    for task_id, requires in plan:
        known = [r for r in requires if r in tasks]
        required.update(known)
        if known:
            builder.add_edge([node_name(r) for r in known], node_name(task_id))
        else:
            builder.add_edge(START, node_name(task_id))
    for task_id in tasks - required:
        builder.add_edge(node_name(task_id), END)
    return builder.compile(checkpointer=checkpointer)
