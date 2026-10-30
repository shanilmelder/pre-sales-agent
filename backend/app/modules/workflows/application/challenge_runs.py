"""A Challenge's reassessment run (Story 9.6; FR-38): its non-agent nodes' work.

A `challenge` run (`queue_run` with `run_type=challenge`) plans the confirmed specialists,
then `conflict_detection`, the Critic and `new_version`. The two non-agent nodes go through
the same node wrapper as an Agent's task (`app.orchestration`), with no model call: their
executor's `accept` calls one of these inside the node's Unit of Work, which also marks the
task done.

- `detect_challenge_conflicts`: the Conflict rules over the current Assessments (the reruns
  included) and the current Estimate, and the semantic detection queued, as a finished
  assessment run does.
- `write_challenge_version`: under the Opportunity's lock, the new Estimate Version from the
  challenged one (`estimates.challenge_lines`: the lines a confirmed agent's rerun resized
  are rebuilt, the rest copied) through `estimates.create_version_from_run` with the key
  `node:<run>:<task>:<attempt>`; then `reviews.complete_challenge` (the Challenge
  `completed`, the challenged version's open Review Requests superseded, the trace with the
  delta, the Inbox items). A replay finds the version already stored for the run and the
  Challenge already completed, so nothing is written twice. When a version newer than the one
  the plan pinned exists, nothing is stored and the task fails `estimate_changed`; the run's
  end then fails the Challenge (`runs._end_challenge`).

Logs carry ids and counts only.
"""

from uuid import UUID

from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import RunErrorCode
from app.modules.estimates.application import public as estimates
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.application.runs import detect_conflicts, run_starter
from app.modules.workflows.application.tasks import NodeTask, fail_task
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)


def node_key(run_id: UUID, task_id: UUID, attempt: int) -> str:
    """The `new_version` node's idempotency key."""
    return f"node:{run_id}:{task_id}:{attempt}"


async def detect_challenge_conflicts(uow: UnitOfWork, task: NodeTask) -> None:
    """The `conflict_detection` node's work (module docstring)."""
    await estimates.lock_for_decision(uow, task.opportunity_id)
    await detect_conflicts(uow, task.opportunity_id, task.run_id)


async def _latest_at_start(uow: UnitOfWork, run_id: UUID) -> int | None:
    for plan in await repo.plan_versions_of(uow, run_id):
        if plan.version == 1 and plan.pins is not None:
            found = plan.pins.get("latest_estimate_version")
            return found if isinstance(found, int) else None
    return None


async def write_challenge_version(uow: UnitOfWork, task: NodeTask) -> bool:
    """The `new_version` node's work (module docstring). False when the Estimate changed
    while the run worked (the task is then `failed`, `estimate_changed`)."""
    # Imported here: reviews starts challenge runs through this module's public API.
    from app.modules.reviews.application import public as reviews

    ids = {"run_id": str(task.run_id), "task_id": str(task.id)}
    if task.trigger_ref is None:  # pragma: no cover - a challenge run has its Challenge
        raise LookupError("A challenge run without its Challenge")
    challenge = await reviews.challenge_run(uow, task.trigger_ref)
    if challenge is None:  # pragma: no cover - Challenges are never deleted
        raise LookupError(f"No Challenge {task.trigger_ref}")
    await estimates.lock_for_decision(uow, task.opportunity_id)
    confirmed = set(challenge.confirmed)
    pairs = [
        (before, after)
        for before, after in await assessments.run_sizing_pairs(
            uow, task.opportunity_id, task.run_id
        )
        if after.agent in confirmed
    ]
    lines = await estimates.challenge_lines(
        uow,
        task.opportunity_id,
        challenge.estimate_version_id,
        pairs,
        await assessments.current_sizings(uow, task.opportunity_id),
    )
    stored = await estimates.create_version_from_run(
        uow,
        task.run_id,
        challenge.estimate_version_id,
        lines,
        challenge.reason,
        node_key(task.run_id, task.id, task.attempt),
        latest_at_start=await _latest_at_start(uow, task.run_id),
        created_by=await run_starter(uow, task.run_id),
    )
    if stored.estimate_changed or stored.version_id is None:
        await fail_task(uow, task.id, RunErrorCode.ESTIMATE_CHANGED.value)
        _log.info("workflows.challenge_estimate_changed", extra=ids)
        return False
    completed = await reviews.complete_challenge(
        uow, challenge.id, run_id=task.run_id, new_version_id=stored.version_id
    )
    _log.info(
        "workflows.challenge_version_written",
        extra={
            **ids,
            "version_id": str(stored.version_id),
            "version_created": stored.created,
            "challenge_completed": completed,
        },
    )
    return True
