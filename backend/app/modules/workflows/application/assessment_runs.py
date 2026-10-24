"""The assessment run query and commands behind the unchanged Assessments API (Story 5.2;
moved from `assessments`, Epic 5 slice 5A and Story 5.5).

- `get_assessments`: the Opportunity's latest run with its tasks, its decisions and plan
  versions, and per agent its current Assessment (read through `assessments`' public API),
  anyone who can read the Opportunity.
- `start_run`: queue a new run with one task per agent (`assessments.assessment.start`: the
  owner and collaborators except sales representatives; other readers 403, everyone else
  the Opportunity's 404). 409 `assessment_in_progress` while one is queued, running or
  waiting for a person; one past `stale_after()` is failed (`model_timeout`) first, so it
  never blocks.
- `retry_task`: re-run one `failed` task of the latest run (same action). 409
  `assessment_in_progress` while a run is queued, running or waiting, 409
  `assessment_task_not_failed` unless that task is `failed` in the latest run (never in a
  cancelled one); 404 for a run that isn't the Opportunity's.
- `cancel_run`: cancel the Opportunity's latest run while it is queued, running or waiting
  for a person (same action). 409 `assessment_not_in_progress` otherwise; 404 for a run
  that isn't the Opportunity's.
- `resolve_decision` (Story 5.5): a person resolves an open decision of the latest run
  while it waits (`workflows.decision.resolve`: the owner and collaborators except sales
  representatives). `If-Match` carries the decision's `row_version`: 428 without it, 412
  "Already resolved by {name}." when stale; 409 `decision_not_open` when the decision is
  not open, its run was cancelled, or the run isn't waiting; 409 `registry_agent_disabled`
  for Re-plan while the Agent is still inactive. In one Unit of Work under the run lock it
  records the choice (Re-plan also re-pins the task to the Agent's current config version
  and writes plan version n+1), queues the run again with a `workflows.resume` job, writes
  a progress row and traces `workflows.decision.resolved`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import RunErrorCode
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.modules.registry.application import public as registry
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import (
    DecisionRecord,
    PlannedTask,
    PlanVersionRecord,
    RunRecord,
    TaskRecord,
)
from app.modules.workflows.application import progress
from app.modules.workflows.application.models import (
    AssessmentRun,
    AssessmentsView,
    AssessmentTask,
    DecisionResolution,
    PlanVersion,
    PlanVersionTask,
    RunDecision,
)
from app.modules.workflows.application.runs import (
    cancel,
    enqueue_resume,
    fail_stale,
    queue_run,
    requeue_task,
    stale_after,
)
from app.modules.workflows.domain.runs import (
    RUN_ACTIVE,
    RUN_IN_PROGRESS,
    RUN_SUBJECT_TYPE,
    TASK_IN_PROGRESS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    DecisionChoice,
    DecisionKind,
    DecisionStatus,
    TaskAgent,
    TaskSkipReason,
    run_status,
    task_agent_rank,
)
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    AssessmentInProgressError,
    AssessmentNotInProgressError,
    AssessmentTaskNotFailedError,
    DecisionNotOpenError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
)
from app.platform.logging import get_logger
from app.platform.trace.catalogue import WorkflowsDecisionResolved
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "An assessment is already running for this Opportunity."
NOT_FAILED_DETAIL = "Only a failed task of the latest assessment run can be retried."
NOT_IN_PROGRESS_DETAIL = (
    "Only the latest assessment run can be cancelled, while it is queued, running or waiting."
)
RUN_NOT_FOUND_DETAIL = "No such assessment run for this Opportunity."
DECISION_NOT_FOUND_DETAIL = "No such decision for this assessment run."
DECISION_NOT_OPEN_DETAIL = "This decision is no longer open."
RUN_NOT_WAITING_DETAIL = "The run isn't waiting for this decision."
SOMEONE_ELSE = "someone else"
MAX_ROW_VERSION = 2**31 - 1
_log = get_logger(__name__)


def _agent_order(agent: str) -> int:
    return task_agent_rank(agent)


@dataclass(frozen=True, slots=True)
class _RunExtras:
    """What a run's view reads besides the run and its tasks (Story 5.5)."""

    decisions: Sequence[RunDecision] = ()
    plan_versions: Sequence[PlanVersion] = ()


def run_view(
    record: RunRecord, tasks: Sequence[TaskRecord], extras: _RunExtras | None = None
) -> AssessmentRun:
    """The read model of a run. One still queued or running past `stale_after()` is lost: its
    unfinished tasks read as failed with `model_timeout` and the run's status follows from
    its tasks', so it can be started again (`start_run` records that). A run waiting for a
    person is never lost. Tasks keep their timestamps either way."""
    extras = extras or _RunExtras()
    lost = (
        AssessmentRunStatus(record.status) in RUN_IN_PROGRESS
        and datetime.now(UTC) - record.queued_at > stale_after()
    )
    views: list[AssessmentTask] = []
    for task in sorted(tasks, key=lambda t: _agent_order(t.agent)):
        status = AssessmentTaskStatus(task.status)
        code = None if task.error_code is None else RunErrorCode(task.error_code)
        if lost and status in TASK_IN_PROGRESS:
            status, code = AssessmentTaskStatus.FAILED, RunErrorCode.MODEL_TIMEOUT
        views.append(
            AssessmentTask(
                agent=TaskAgent(task.agent),
                status=status,
                error_code=code,
                skip_reason=(
                    None if task.skip_reason is None else TaskSkipReason(task.skip_reason)
                ),
                started_at=task.started_at,
                finished_at=task.finished_at,
            )
        )
    overall = run_status(t.status for t in views) if lost else AssessmentRunStatus(record.status)
    return AssessmentRun(
        id=str(record.id),
        status=overall,
        created_at=record.created_at,
        queued_at=record.queued_at,
        finished_at=record.finished_at,
        tasks=views,
        plan_version=record.plan_version,
        decisions=list(extras.decisions),
        plan_versions=list(extras.plan_versions),
    )


async def _names(uow: UnitOfWork, ids: set[UUID]) -> dict[UUID, str]:
    return await identity.user_names(uow, ids) if ids else {}


def _user_id(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


async def _extras(
    uow: UnitOfWork,
    tasks: Sequence[TaskRecord],
    decisions: Sequence[DecisionRecord],
    plans: Sequence[PlanVersionRecord],
) -> _RunExtras:
    agents = {t.id: t.agent for t in tasks}
    registered = {
        agent: await registry.current_config(uow, agent)
        for agent in sorted({agents[d.task_id] for d in decisions if d.task_id in agents})
    }
    plan_users = {
        uid
        for p in plans
        if p.created_by_type == "user" and (uid := _user_id(p.created_by)) is not None
    }
    names = await _names(
        uow, {d.resolved_by for d in decisions if d.resolved_by is not None} | plan_users
    )
    versions = await registry.get_config_versions(
        uow, sorted({t.config_version_id for p in plans for t in p.tasks})
    )
    decision_views = [
        RunDecision(
            id=str(d.id),
            kind=DecisionKind(d.kind),
            agent=TaskAgent(agents[d.task_id]),
            agent_name=registered[agents[d.task_id]].name,
            agent_active=registered[agents[d.task_id]].runs_tasks,
            status=DecisionStatus(d.status),
            choice=None if d.choice is None else DecisionChoice(d.choice),
            row_version=d.row_version,
            created_at=d.created_at,
            resolved_by=(None if d.resolved_by is None else names.get(d.resolved_by, SOMEONE_ELSE)),
            resolved_at=d.resolved_at,
        )
        for d in decisions
        if d.task_id in agents
    ]
    plan_views = []
    for plan in plans:
        uid = _user_id(plan.created_by) if plan.created_by_type == "user" else None
        plan_views.append(
            PlanVersion(
                version=plan.version,
                created_by=None if uid is None else names.get(uid, SOMEONE_ELSE),
                created_at=plan.created_at,
                tasks=[
                    PlanVersionTask(
                        agent=TaskAgent(t.agent),
                        config_version_id=str(t.config_version_id),
                        config_version=(
                            versions[t.config_version_id].version
                            if t.config_version_id in versions
                            else None
                        ),
                        semver=(
                            versions[t.config_version_id].semver
                            if t.config_version_id in versions
                            else None
                        ),
                    )
                    for t in sorted(plan.tasks, key=lambda t: _agent_order(t.agent))
                ],
            )
        )
    return _RunExtras(decisions=decision_views, plan_versions=plan_views)


async def _full_view(uow: UnitOfWork, record: RunRecord) -> AssessmentRun:
    tasks = await repo.tasks_of(uow, record.id)
    extras = await _extras(
        uow,
        tasks,
        await repo.decisions_of(uow, record.id),
        await repo.plan_versions_of(uow, record.id),
    )
    return run_view(record, tasks, extras)


async def latest_run_view(uow: UnitOfWork, opportunity_id: UUID) -> AssessmentRun | None:
    """The Opportunity's latest run (null before the first). No authorization."""
    latest = await repo.latest_run(uow, opportunity_id)
    return None if latest is None else await _full_view(uow, latest)


async def get_assessments(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> AssessmentsView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    return AssessmentsView(
        run=await latest_run_view(uow, opportunity_id),
        assessments=await assessments.agent_assessments(uow, opportunity_id),
        can_start=identity.can(actor, Action.ASSESSMENT_START, resource),
        can_resolve=identity.can(actor, Action.DECISION_RESOLVE, resource),
    )


async def _current_run(uow: UnitOfWork, run_id: UUID) -> AssessmentRun:
    record = await repo.get_run(uow, run_id)
    assert record is not None  # inserted or locked in this Unit of Work
    return await _full_view(uow, record)


async def start_run(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> AssessmentRun:
    """Queue a new assessment run of the Opportunity: one task per specialist agent."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    if await repo.run_active(uow, opportunity_id) is not None:
        raise AssessmentInProgressError(IN_PROGRESS_DETAIL)
    run_id = await queue_run(uow, opportunity_id, actor.actor)
    _log.info(
        "workflows.run_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "actor_id": actor.actor.id,
        },
    )
    return await _current_run(uow, run_id)


async def retry_task(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    run_id: UUID,
    agent: TaskAgent,
) -> AssessmentRun:
    """Re-run one failed task of the Opportunity's latest assessment run."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    record = await repo.get_run(uow, run_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    await fail_stale(uow, opportunity_id)
    if await repo.run_active(uow, opportunity_id) is not None:
        raise AssessmentInProgressError(IN_PROGRESS_DETAIL)
    latest = await repo.latest_run(uow, opportunity_id)
    task = await repo.get_task(uow, run_id, agent.value)
    if (
        latest is None
        or latest.id != run_id
        # A cancelled run is final: re-queueing a task that failed before the cancel would
        # revive it.
        or latest.status == AssessmentRunStatus.CANCELLED
        or task is None
        or task.status != AssessmentTaskStatus.FAILED
    ):
        raise AssessmentTaskNotFailedError(NOT_FAILED_DETAIL)
    await registry.require_enabled(uow, agent.value)  # 409 while the agent is disabled
    await requeue_task(uow, latest, agent.value, actor.actor)
    _log.info(
        "workflows.task_retried",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "agent": agent.value,
            "actor_id": actor.actor.id,
        },
    )
    return await _current_run(uow, run_id)


async def cancel_run(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, run_id: UUID
) -> AssessmentRun:
    """Cancel the Opportunity's latest assessment run while it is queued, running or
    waiting for a person."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    record = await repo.get_run(uow, run_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    await fail_stale(uow, opportunity_id)
    latest = await repo.latest_run(uow, opportunity_id)
    if (
        latest is None
        or latest.id != run_id
        or AssessmentRunStatus(latest.status) not in RUN_ACTIVE
        # Every task already finished: the job is about to record the outcome.
        or not any(
            AssessmentTaskStatus(t.status) in TASK_IN_PROGRESS
            for t in await repo.tasks_of(uow, run_id)
        )
    ):
        raise AssessmentNotInProgressError(NOT_IN_PROGRESS_DETAIL)
    skipped, succeeded = await cancel(uow, latest, actor.actor)
    _log.info(
        "workflows.run_cancelled",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "actor_id": actor.actor.id,
            "skipped_count": skipped,
            "succeeded_count": succeeded,
        },
    )
    return await _current_run(uow, run_id)


# --- resolving a decision (Story 5.5) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedDecision:
    """The run as it is after the decision, and the decision's new `row_version` (its
    ETag)."""

    run: AssessmentRun
    row_version: int


async def _stale(uow: UnitOfWork, decision: DecisionRecord) -> RowVersionMismatchError:
    name = SOMEONE_ELSE
    if decision.resolved_by is not None:
        name = (await _names(uow, {decision.resolved_by})).get(decision.resolved_by, name)
    return RowVersionMismatchError(f"Already resolved by {name}.")


async def resolve_decision(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    run_id: UUID,
    decision_id: UUID,
    resolution: DecisionResolution,
    if_match: str | None,
) -> ResolvedDecision:
    """Resolve an open decision of the Opportunity's waiting run (see the module
    docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.DECISION_RESOLVE, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can resolve decisions.")
    await repo.lock_runs(uow, opportunity_id)
    record = await repo.get_run(uow, run_id, for_update=True)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    decision = await repo.get_decision(uow, decision_id, for_update=True)
    if decision is None or decision.run_id != run_id:
        raise NotFoundError(DECISION_NOT_FOUND_DETAIL)
    expected = parse_if_match(if_match)  # 428 without; 412 for a malformed one
    if (
        decision.status == DecisionStatus.CANCELLED
        or record.status == AssessmentRunStatus.CANCELLED
    ):
        raise DecisionNotOpenError(DECISION_NOT_OPEN_DETAIL)
    if expected >= MAX_ROW_VERSION or decision.row_version != expected:
        raise await _stale(uow, decision)
    if decision.status != DecisionStatus.OPEN:
        raise DecisionNotOpenError(DECISION_NOT_OPEN_DETAIL)
    if record.status != AssessmentRunStatus.WAITING_FOR_HUMAN:
        raise DecisionNotOpenError(RUN_NOT_WAITING_DETAIL)
    task = await repo.get_task_by_id(uow, decision.task_id)
    assert task is not None  # the decision's foreign key
    choice = resolution.choice

    plan_version = record.plan_version
    if choice == DecisionChoice.REPLAN:
        agent = await registry.require_enabled(uow, task.agent)  # 409 while still inactive
        await repo.repin_task(uow, task.id, agent.current.id)
        plan_version = record.plan_version + 1
        await repo.set_plan_version(uow, run_id, plan_version)
        await repo.insert_plan_version(
            uow,
            run_id=run_id,
            version=plan_version,
            tasks=[
                PlannedTask(t.id, t.agent, t.config_version_id, t.after)
                for t in await repo.tasks_of(uow, run_id)
            ],
            actor=actor.actor,
        )

    new_version = await repo.resolve_decision(
        uow, decision.id, expected_row_version=expected, choice=choice.value, user_id=user_id
    )
    if new_version is None:  # pragma: no cover - the run lock and row lock serialise resolves
        raise await _stale(uow, decision)
    await repo.set_run_status(
        uow,
        run_id,
        from_statuses=(AssessmentRunStatus.WAITING_FOR_HUMAN.value,),
        status=AssessmentRunStatus.QUEUED.value,
        requeued=True,
    )
    await enqueue_resume(uow, record)
    await progress.run_changed(
        uow, opportunity_id=opportunity_id, run_id=run_id, status=AssessmentRunStatus.QUEUED
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=WorkflowsDecisionResolved(
            decision_id=str(decision.id),
            task_id=str(task.id),
            agent=task.agent,
            kind=DecisionKind(decision.kind).value,
            choice=choice.value,
            plan_version=plan_version,
            row_version=new_version,
        ),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "workflows.decision_resolved",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "decision_id": str(decision.id),
            "agent": task.agent,
            "choice": choice.value,
            "plan_version": plan_version,
            "actor_id": actor.actor.id,
        },
    )
    return ResolvedDecision(run=await _current_run(uow, run_id), row_version=new_version)


async def resolved_choices(uow: UnitOfWork, run_id: UUID) -> dict[str, str]:
    """`{decision_id: choice}` for the run's resolved decisions (for the graph runner's
    resume). No authorization."""
    return {
        str(d.id): d.choice
        for d in await repo.decisions_of(uow, run_id)
        if d.status == DecisionStatus.RESOLVED and d.choice is not None
    }
