"""The specialist Assessments query and commands (Epic 5 slice 5A).

- `get_assessments`: the Opportunity's latest assessment run with its tasks, and per agent
  its current Assessment (or null) with the Findings ranked critical to low (then by
  position), each with its Requirement chips (label and excerpt), and the effort rows in
  Requirement order with the total hours (anyone who can read the Opportunity). Superseded
  Assessments are hidden.
- `start_run`: queue a new run with one task per agent (`assessments.assessment.start`: the
  owner and collaborators except sales representatives; other readers 403, everyone else
  the Opportunity's 404). 409 `assessment_in_progress` while one is queued or running; one
  past `stale_after()` is failed (`model_timeout`) first, so it never blocks.
- `retry_task`: re-run one `failed` task of the latest run (same action). 409
  `assessment_in_progress` while the run is queued or running, 409
  `assessment_task_not_failed` unless that task is `failed` in the latest run; 404 for a run
  that isn't the Opportunity's.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.modules.assessments.adapters import assessment_repository as repo
from app.modules.assessments.adapters.assessment_repository import (
    AssessmentRecord,
    EffortRecord,
    FindingRecord,
    RunRecord,
    TaskRecord,
)
from app.modules.assessments.application.assessment import (
    fail_stale,
    queue_run,
    requeue_task,
    stale_after,
)
from app.modules.assessments.application.models import (
    AgentAssessment,
    AssessmentEffort,
    AssessmentFinding,
    AssessmentRun,
    AssessmentsView,
    AssessmentTask,
    AssessmentView,
    FindingRequirement,
    SeverityCounts,
)
from app.modules.assessments.domain.assessments import (
    AGENTS,
    RUN_IN_PROGRESS,
    TASK_IN_PROGRESS,
    AssessmentAgent,
    AssessmentRunStatus,
    AssessmentStatus,
    AssessmentTaskStatus,
    Confidence,
    FindingKind,
    Recommendation,
    run_status,
    total_hours,
)
from app.modules.assessments.domain.reviews import (
    RunErrorCode,
    Severity,
    excerpt,
    severity_counts,
    severity_rank,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import (
    AssessmentInProgressError,
    AssessmentTaskNotFailedError,
    NotFoundError,
)
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "An assessment is already running for this Opportunity."
NOT_FAILED_DETAIL = "Only a failed task of the latest assessment run can be retried."
RUN_NOT_FOUND_DETAIL = "No such assessment run for this Opportunity."
INACTIVE_LABEL = "Superseded"
_log = get_logger(__name__)


def _agent_order(agent: str) -> int:
    try:
        return AGENTS.index(AssessmentAgent(agent))
    except ValueError:  # pragma: no cover - the table only holds known agents
        return len(AGENTS)


def run_view(record: RunRecord, tasks: Sequence[TaskRecord]) -> AssessmentRun:
    """The read model of a run. One still queued or running past `stale_after()` is lost: its
    unfinished tasks read as failed with `model_timeout` and the run's status follows from
    its tasks', so it can be started again (`start_run` records that)."""
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
            AssessmentTask(agent=AssessmentAgent(task.agent), status=status, error_code=code)
        )
    overall = run_status(t.status for t in views) if lost else AssessmentRunStatus(record.status)
    return AssessmentRun(
        id=str(record.id), status=overall, created_at=record.created_at, tasks=views
    )


async def _chips(
    uow: UnitOfWork, opportunity_id: UUID, refs: set[tuple[UUID, int]]
) -> tuple[dict[tuple[UUID, int], FindingRequirement], dict[UUID, int]]:
    """Requirement chips for `(id, version)` refs, and each active Requirement's number."""
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(uow, opportunity_id, list(refs))
    chips: dict[tuple[UUID, int], FindingRequirement] = {}
    for requirement_id, version in refs:
        number = active.get(requirement_id)
        found = texts.get((requirement_id, version))
        chips[(requirement_id, version)] = FindingRequirement(
            id=str(requirement_id),
            version=version,
            label=f"R{number}" if number is not None else INACTIVE_LABEL,
            excerpt="" if found is None else excerpt(found.text),
        )
    return chips, active


async def _views(
    uow: UnitOfWork, opportunity_id: UUID, records: Sequence[AssessmentRecord]
) -> dict[str, AssessmentView]:
    """Each Assessment with its ranked Findings, their chips, its effort and the counts."""
    ids = [r.id for r in records]
    findings = await repo.findings_of(uow, ids)
    links = await repo.requirement_links_for(uow, [f.id for f in findings])
    effort = await repo.effort_of(uow, ids)
    refs = {(link.requirement_id, link.requirement_version) for link in links} | {
        (e.requirement_id, e.requirement_version) for e in effort
    }
    chips, active = await _chips(uow, opportunity_id, refs)

    def order(requirement_id: UUID) -> tuple[int, str]:
        return (active.get(requirement_id, len(active) + 1), str(requirement_id))

    cited: dict[UUID, list[FindingRequirement]] = defaultdict(list)
    for link in sorted(links, key=lambda link: order(link.requirement_id)):
        cited[link.finding_id].append(chips[(link.requirement_id, link.requirement_version)])
    by_assessment: dict[UUID, list[FindingRecord]] = defaultdict(list)
    for f in findings:
        by_assessment[f.assessment_id].append(f)
    effort_by: dict[UUID, list[EffortRecord]] = defaultdict(list)
    for e in sorted(effort, key=lambda e: order(e.requirement_id)):
        effort_by[e.assessment_id].append(e)

    views: dict[str, AssessmentView] = {}
    for record in records:
        own = by_assessment.get(record.id, [])
        rows = effort_by.get(record.id, [])
        counts = severity_counts(Severity(f.severity) for f in own)
        views[record.agent] = AssessmentView(
            id=str(record.id),
            agent=AssessmentAgent(record.agent),
            version=record.version,
            status=AssessmentStatus(record.status),
            run_id=str(record.run_id),
            recommendation=Recommendation(record.recommendation),
            confidence=Confidence(record.confidence),
            confidence_basis=record.confidence_basis,
            dropped_count=record.dropped_count,
            created_at=record.created_at,
            counts=SeverityCounts(
                critical=counts[Severity.CRITICAL],
                high=counts[Severity.HIGH],
                medium=counts[Severity.MEDIUM],
                low=counts[Severity.LOW],
            ),
            findings=[
                AssessmentFinding(
                    id=str(f.id),
                    position=f.position,
                    kind=FindingKind(f.kind),
                    severity=Severity(f.severity),
                    title=f.title,
                    detail=f.detail,
                    requirements=cited.get(f.id, []),
                )
                for f in sorted(own, key=lambda f: (severity_rank(f.severity), f.position))
            ],
            effort=[
                AssessmentEffort(
                    requirement=chips[(e.requirement_id, e.requirement_version)],
                    hours=float(e.hours),
                    basis=e.basis,
                )
                for e in rows
            ],
            total_hours=float(total_hours(Decimal(e.hours) for e in rows)),
        )
    return views


async def get_assessments(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> AssessmentsView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    latest = await repo.latest_run(uow, opportunity_id)
    run = None if latest is None else run_view(latest, await repo.tasks_of(uow, latest.id))
    views = await _views(uow, opportunity_id, await repo.current_assessments(uow, opportunity_id))
    return AssessmentsView(
        run=run,
        assessments=[
            AgentAssessment(agent=agent, assessment=views.get(agent.value)) for agent in AGENTS
        ],
        can_start=identity.can(actor, Action.ASSESSMENT_START, resource),
    )


async def _current_run(uow: UnitOfWork, run_id: UUID) -> AssessmentRun:
    record = await repo.get_run(uow, run_id)
    assert record is not None  # inserted or locked in this Unit of Work
    return run_view(record, await repo.tasks_of(uow, run_id))


async def start_run(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> AssessmentRun:
    """Queue a new assessment run of the Opportunity: one task per specialist agent."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    if await repo.run_in_progress(uow, opportunity_id) is not None:
        raise AssessmentInProgressError(IN_PROGRESS_DETAIL)
    run_id = await queue_run(uow, opportunity_id, actor.actor)
    _log.info(
        "assessments.assessment_run_started",
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
    agent: AssessmentAgent,
) -> AssessmentRun:
    """Re-run one failed task of the Opportunity's latest assessment run."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    record = await repo.get_run(uow, run_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    await fail_stale(uow, opportunity_id)
    if await repo.run_in_progress(uow, opportunity_id) is not None:
        raise AssessmentInProgressError(IN_PROGRESS_DETAIL)
    latest = await repo.latest_run(uow, opportunity_id)
    task = await repo.get_task(uow, run_id, agent.value)
    if (
        latest is None
        or latest.id != run_id
        or task is None
        or task.status != AssessmentTaskStatus.FAILED
    ):
        raise AssessmentTaskNotFailedError(NOT_FAILED_DETAIL)
    await requeue_task(uow, latest, agent, actor.actor)
    _log.info(
        "assessments.assessment_task_retried",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "agent": agent.value,
            "actor_id": actor.actor.id,
        },
    )
    return await _current_run(uow, run_id)
