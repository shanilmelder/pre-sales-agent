"""The graph runner (AD-6, AD-7; Story 5.2), installed by the worker as `workflows`' graph
runner hook.

For a run, it builds the graph from the run's plan and invokes it on the thread
`thread_id = run_id`, checkpointed after every superstep (`durability="sync"`):

- the thread has pending `next` nodes (the previous attempt was interrupted mid-run, e.g.
  the worker was killed and the job reclaimed) and every unfinished task is among them (or
  waits on one): it resumes with `None` input, so nodes whose writes were saved are not run
  again;
- otherwise (a new run, a finished attempt whose tasks failed, a manual task retry): it
  starts a fresh invocation on the same thread; nodes whose tasks already finished re-read
  them and do nothing.

Returns the errors the nodes reported. The checkpointer comes from `checkpointers`, an async
context manager factory: the worker shares one pool for the process; tests open one per
call.
"""

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.modules.workflows.application import public as workflows
from app.modules.workflows.application.public import GraphRun
from app.orchestration.checkpointer import open_checkpointer
from app.orchestration.graph import Invocation, build_graph, node_name
from app.platform.logging import get_logger
from app.platform.uow import unit_of_work

_log = get_logger(__name__)

CheckpointerFactory = Callable[[], AbstractAsyncContextManager[BaseCheckpointSaver[Any]]]


def thread_config(run_id: object, task_count: int) -> RunnableConfig:
    return {
        "configurable": {"thread_id": str(run_id)},
        # Every task is one superstep at most; a little slack for the START step.
        "recursion_limit": task_count + 5,
    }


def _unaccounted(
    plan: Sequence[tuple[UUID, tuple[UUID, ...]]],
    values: dict[str, Any],
    pending: Sequence[str],
) -> list[UUID]:
    """Tasks a resume would never run: not finished, not pending, yet every task they
    require finished (so their node already ran, e.g. failing on an earlier attempt, before
    the interruption). With any, the run starts a fresh invocation on its thread instead."""
    finished = {UUID(t) for t in values.get("finished", [])}
    waiting = set(pending)
    tasks = {task_id for task_id, _ in plan}
    return [
        task_id
        for task_id, requires in plan
        if task_id not in finished
        and node_name(task_id) not in waiting
        and all(r in finished for r in requires if r in tasks)
    ]


class LangGraphRunner:
    """`workflows.GraphRunner`: executes a run's graph with the Postgres checkpointer."""

    def __init__(self, checkpointers: CheckpointerFactory) -> None:
        self._checkpointers = checkpointers
        self._ready = False

    async def _setup(self, saver: BaseCheckpointSaver[Any]) -> None:
        """Create or migrate the library's tables once (idempotent), on first use, so a
        worker starting while the database is down still starts."""
        if self._ready:
            return
        if isinstance(saver, AsyncPostgresSaver):
            await saver.setup()
        self._ready = True

    async def __call__(self, run: GraphRun) -> Sequence[BaseException]:
        async with unit_of_work(run.engine) as uow:
            plan = await workflows.plan_of(uow, run.run_id)
        if not plan:
            return []
        invocation = Invocation(run=run)
        config = thread_config(run.run_id, len(plan))
        ids = {"run_id": str(run.run_id), "attempt": run.attempt}
        async with self._checkpointers() as saver:
            await self._setup(saver)
            graph = build_graph(plan, invocation, saver)
            snapshot = await graph.aget_state(config)
            if snapshot.next and not _unaccounted(plan, snapshot.values, snapshot.next):
                _log.info("orchestration.run_resumed", extra={**ids, "pending": len(snapshot.next)})
                await graph.ainvoke(None, config, durability="sync")
            else:
                _log.info("orchestration.run_invoked", extra=ids)
                await graph.ainvoke(
                    {"run_id": str(run.run_id), "finished": []}, config, durability="sync"
                )
        _log.info(
            "orchestration.run_returned", extra={**ids, "error_count": len(invocation.errors)}
        )
        return list(invocation.errors)


@asynccontextmanager
async def open_runner(database_url: str) -> AsyncIterator[LangGraphRunner]:
    """The worker's runner: one checkpointer pool for the process, opened here (without
    waiting for a connection) and closed on exit."""
    async with open_checkpointer(database_url, setup=False) as saver:

        @asynccontextmanager
        async def shared() -> AsyncIterator[BaseCheckpointSaver[Any]]:
            yield saver

        yield LangGraphRunner(shared)
