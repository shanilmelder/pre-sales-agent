"""The assessment run query and commands behind the unchanged Assessments API (Story 5.2;
moved from `assessments`, Epic 5 slice 5A and Story 5.5).

- `get_assessments`: the Opportunity's latest run with its tasks, decisions and plan
  versions, and per agent its current Assessment (read through `assessments`' public API),
  anyone who can read the Opportunity.
- `start_run`: queue a new run with one task per agent (`assessments.assessment.start`: the
  owner and collaborators except sales representatives; other readers 403, everyone else
  the Opportunity's 404). 409 `assessment_in_progress` while one is queued, running or
  waiting for a person; one past `stale_after()` is failed (`model_timeout`) first, so it
  never blocks.
- `retry_task`: re-run one `failed` task of the latest run (same action). 409
  `assessment_in_progress` while the run is queued, running or waiting, 409
  `assessment_task_not_failed` unless that task is `failed` in the latest run (never in a
  cancelled one); 404 for a run that isn't the Opportunity's.
- `cancel_run`: cancel the Opportunity's latest run while it is queued, running or waiting
  for a person (same action). 409 `assessment_not_in_progress` otherwise; 404 for a run
  that isn't the Opportunity's.
- `resolve_decision` (Story 5.5): resolve a waiting run's open decision with **Continue
  without** or **Re-plan** (`workflows.decision.resolve`: the owner and collaborators
  except sales representatives). With the decision's `row_version` in `If-Match`: 428
  without; 409 `decision_not_open` when the decision or its run was cancelled; 412 "Already
  resolved by {name}." when stale; 409 `decision_not_open` when the decision is not open or
  the run is not waiting; 409 `registry_agent_disabled` for a Re-plan while the Agent is
  still not active. In one Unit of Work under the run lock it records the choice (a Re-plan
  also re-pins the task to the Agent's current config version and adds a plan version),
  queues the run with a `workflows.resume` job and traces `workflows.decision.resolved`.
"""

from collections.abc import Sequence
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
    PlanVersionRecord,
    RunRecord,
    TaskRecord,
)
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
    fail_stale,
    plan_tasks,
    queue_resume,
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
    chosen_skip,
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
SOMEONE_ELSE = "someone else"
SYSTEM_NAME = "System"
MAX_ROW_VERSION = 2**31 - 1
_log = get_logger(__name__)


def _agent_order(agent: str) -> int:
    return task_agent_rank(agent)


def run_view(
    record: RunRecord,
    tasks: Sequence[TaskRecord],
    decisions: Sequence[RunDecision] = (),
    plan_versions: Sequence[PlanVersion] = (),
) -> AssessmentRun:
    """The read model of a run. One still queued or running past `stale_after()` is lost: its
    unfinished tasks read as failed with `model_timeout` and the run's status follows from
    its tasks', so it can be started again (`start_run` records that). A run waiting for a
    person is never lost. Tasks keep their timestamps either way."""
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
    chosen = sum(1 for t in views if chosen_skip(t.status, t.skip_reason))
    overall = (
        run_status([t.status for t in views], chosen_skips=chosen)
        if lost
        else AssessmentRunStatus(record.status)
    )
    return AssessmentRun(
        id=str(record.id),
        status=overall,
        created_at=record.created_at,
        queued_at=record.queued_at,
        finished_at=record.finished_at,
        tasks=views,
        plan_version=record.plan_version,
        decisions=list(decisions),
        plan_versions=list(plan_versions),
    )


def _user_id(actor_id: str) -> UUID | None:
    try:
        return UUID(actor_id)
    except ValueError:
        return None


async def _decision_views(
    uow: UnitOfWork,
    decisions: Sequence[DecisionRecord],
    tasks: Sequence[TaskRecord],
    names: dict[UUID, str],
) -> list[RunDecision]:
    agents = {t.id: t.agent for t in tasks}
    registered = {
        agent: await registry.current_config(uow, agent)
        for agent in sorted({agents[d.task_id] for d in decisions if d.task_id in agents})
    }
    views: list[RunDecision] = []
    for decision in decisions:
        agent = agents.get(decision.task_id)
        if agent is None:  # pragma: no cover - a decision's task is one of its run's
            continue
        views.append(
            RunDecision(
                id=str(decision.id),
                kind=DecisionKind(decision.kind),
                agent=TaskAgent(agent),
                agent_name=registered[agent].name,
                agent_active=registered[agent].runs_tasks,
                status=DecisionStatus(decision.status),
                choice=None if decision.choice is None else DecisionChoice(decision.choice),
                row_version=decision.row_version,
                created_at=decision.created_at,
                resolved_by=(
                    None
                    if decision.resolved_by is None
                    else names.get(decision.resolved_by, SOMEONE_ELSE)
                ),
                resolved_at=decision.resolved_at,
            )
        )
    return views


async def _plan_views(
    uow: UnitOfWork, plans: Sequence[PlanVersionRecord], names: dict[UUID, str]
) -> list[PlanVersion]:
    versions = await registry.get_config_versions(
        uow, sorted({t.config_version_id for p in plans for t in p.tasks})
    )
    views: list[PlanVersion] = []
    for plan in plans:
        if plan.created_by_type == "user":
            user_id = _user_id(plan.created_by)
            who = SOMEONE_ELSE if user_id is None else names.get(user_id, SOMEONE_ELSE)
        else:
            who = SYSTEM_NAME
        views.append(
            PlanVersion(
                version=plan.version,
                created_by=who,
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
                    )
                    for t in sorted(plan.tasks, key=lambda t: _agent_order(t.agent))
                ],
            )
        )
    return views


async def full_run_view(uow: UnitOfWork, record: RunRecord) -> AssessmentRun:
    """`run_view` with the run's decisions and plan versions."""
    tasks = await repo.tasks_of(uow, record.id)
    decisions = await repo.decisions_of(uow, record.id)
    plans = await repo.plan_versions_of(uow, record.id)
    people = {d.resolved_by for d in decisions if d.resolved_by is not None} | {
        user_id
        for p in plans
        if p.created_by_type == "user" and (user_id := _user_id(p.created_by)) is not None
    }
    names = await identity.user_names(uow, people) if people else {}
    return run_view(
        record,
        tasks,
        await _decision_views(uow, decisions, tasks, names),
        await _plan_views(uow, plans, names),
    )


async def latest_run_view(uow: UnitOfWork, opportunity_id: UUID) -> AssessmentRun | None:
    """The Opportunity's latest run (null before the first). No authorization."""
    latest = await repo.latest_run(uow, opportunity_id)
    return None if latest is None else await full_run_view(uow, latest)


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
    return await full_run_view(uow, record)


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
    """Cancel the Opportunity's latest assessment run while it is queued, running or waiting
    for a person."""
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


# --- resolving a decision (Story 5.5) ---------------------------------------------------------


async def _stale(uow: UnitOfWork, decision: DecisionRecord) -> RowVersionMismatchError:
    name = SOMEONE_ELSE
    if decision.resolved_by is not None:
        name = (await identity.user_names(uow, {decision.resolved_by})).get(
            decision.resolved_by, name
        )
    return RowVersionMismatchError(f"Already resolved by {name}.")


async def resolve_decision(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    run_id: UUID,
    decision_id: UUID,
    resolution: DecisionResolution,
    if_match: str | None,
) -> AssessmentRun:
    """Resolve a waiting run's open decision (see the module docstring); the run as it is
    now, queued to resume."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.DECISION_RESOLVE, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants the action to users only
        raise ForbiddenError("Only people can resolve decisions.")
    await repo.lock_runs(uow, opportunity_id)
    run = await repo.get_run(uow, run_id, for_update=True)
    if run is None or run.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    decision = await repo.get_decision(uow, decision_id, for_update=True)
    if decision is None or decision.run_id != run_id:
        raise NotFoundError(DECISION_NOT_FOUND_DETAIL)
    expected = parse_if_match(if_match)
    if decision.status == DecisionStatus.CANCELLED or run.status == AssessmentRunStatus.CANCELLED:
        raise DecisionNotOpenError(DECISION_NOT_OPEN_DETAIL)
    if expected >= MAX_ROW_VERSION or expected != decision.row_version:
        raise await _stale(uow, decision)
    if (
        decision.status != DecisionStatus.OPEN
        or run.status != AssessmentRunStatus.WAITING_FOR_HUMAN
    ):
        raise DecisionNotOpenError(DECISION_NOT_OPEN_DETAIL)
    task = await repo.get_task_by_id(uow, decision.task_id)
    assert task is not None  # the decision's task is one of its run's
    choice = resolution.choice
    config_version_id = task.config_version_id
    plan_version = run.plan_version
    if choice == DecisionChoice.REPLAN:
        agent = await registry.require_enabled(uow, task.agent)  # 409 while still disabled
        config_version_id = agent.current.id
    new_version = await repo.resolve_decision(
        uow,
        decision.id,
        expected_row_version=expected,
        choice=choice.value,
        user_id=user_id,
    )
    if new_version is None:  # pragma: no cover - the run lock serialises resolves
        raise await _stale(uow, decision)
    if choice == DecisionChoice.REPLAN:
        plan_version = run.plan_version + 1
        await repo.repin_task(uow, task.id, config_version_id)
        await repo.set_plan_version(uow, run.id, plan_version)
        await repo.insert_plan_version(
            uow,
            run_id=run.id,
            version=plan_version,
            tasks=await plan_tasks(uow, run.id),
            actor=actor.actor,
        )
    await queue_resume(uow, run)
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
            config_version_id=str(config_version_id),
        ),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run.id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "workflows.decision_resolved",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "decision_id": str(decision_id),
            "actor_id": actor.actor.id,
            "choice": choice.value,
            "plan_version": plan_version,
            "row_version": new_version,
        },
    )
    return await _current_run(uow, run_id)
