"""The Red Team query and start command (Story 6.5).

- `get_red_team`: the Opportunity's current Red Team Review, with its Findings ranked critical
  to low (then by position), each with its Requirement chips (label and excerpt) and its
  Estimate line chips (title and effort), and the counts per severity; and its latest run
  (anyone who can read the Opportunity). Superseded Reviews are hidden.
- `start_review`: queue a new Red Team run, e.g. to retry a failed one
  (`assessments.red_team.start`: the owner and collaborators except sales representatives;
  other readers 403, everyone else the Opportunity's 404). 409
  `red_team_review_in_progress` while one is queued or running; one past `stale_after()` is
  marked failed (`model_timeout`) first, so it never blocks.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from app.modules.assessments.adapters import repository as repo
from app.modules.assessments.adapters.repository import FindingRecord, ReviewRecord, RunRecord
from app.modules.assessments.application.models import (
    FindingLine,
    FindingRequirement,
    RedTeamFinding,
    RedTeamReviewView,
    RedTeamRun,
    RedTeamView,
    SeverityCounts,
)
from app.modules.assessments.application.review import fail_stale, queue_review, stale_after
from app.modules.assessments.domain.reviews import (
    IN_PROGRESS,
    FindingCategory,
    ReviewKind,
    ReviewStatus,
    RunErrorCode,
    RunStatus,
    Severity,
    excerpt,
    severity_counts,
    severity_rank,
)
from app.modules.estimates.application import public as estimates
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import RedTeamReviewInProgressError
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "A Red Team review is already running for this Opportunity."
INACTIVE_LABEL = "Superseded"
_KIND = ReviewKind.RED_TEAM.value
_log = get_logger(__name__)


def _run(record: RunRecord | None) -> RedTeamRun | None:
    """The read model of the latest run. One still queued or running past `stale_after()` is
    lost: it reads as failed with `model_timeout`, so it can be retried (`start_review`
    records that)."""
    if record is None:
        return None
    lost = (
        RunStatus(record.status) in IN_PROGRESS
        and datetime.now(UTC) - record.created_at > stale_after()
    )
    if lost:
        return RedTeamRun(status=RunStatus.FAILED, error_code=RunErrorCode.MODEL_TIMEOUT)
    return RedTeamRun(
        status=RunStatus(record.status),
        error_code=None if record.error_code is None else RunErrorCode(record.error_code),
    )


async def _requirements(
    uow: UnitOfWork, opportunity_id: UUID, findings: list[FindingRecord]
) -> dict[UUID, list[FindingRequirement]]:
    links = await repo.requirement_links_for(uow, [f.id for f in findings])
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(
        uow,
        opportunity_id,
        list({(link.requirement_id, link.requirement_version) for link in links}),
    )
    related: dict[UUID, list[tuple[int, FindingRequirement]]] = defaultdict(list)
    for link in links:
        number = active.get(link.requirement_id)
        found = texts.get((link.requirement_id, link.requirement_version))
        related[link.finding_id].append(
            (
                number if number is not None else len(active) + 1,
                FindingRequirement(
                    id=str(link.requirement_id),
                    version=link.requirement_version,
                    label=f"R{number}" if number is not None else INACTIVE_LABEL,
                    excerpt="" if found is None else excerpt(found.text),
                ),
            )
        )
    return {
        finding_id: [r for _, r in sorted(items, key=lambda pair: (pair[0], pair[1].id))]
        for finding_id, items in related.items()
    }


async def review_view(uow: UnitOfWork, record: ReviewRecord) -> RedTeamReviewView:
    """The Review with its ranked Findings, their chips and the counts per severity."""
    findings = await repo.findings_of(uow, record.id)
    cited = await _requirements(uow, record.opportunity_id, findings)
    estimate = (
        None
        if record.estimate_version_id is None
        else await estimates.version_lines(uow, record.opportunity_id, record.estimate_version_id)
    )
    known_lines = {} if estimate is None else {line.id: line for line in estimate.lines}
    order = {line_id: n for n, line_id in enumerate(known_lines)}
    challenged: dict[UUID, list[FindingLine]] = defaultdict(list)
    for link in sorted(
        await repo.line_links_for(uow, [f.id for f in findings]),
        key=lambda link: order.get(link.line_id, len(order)),
    ):
        line = known_lines.get(link.line_id)
        if line is None:  # pragma: no cover - lines are never deleted
            continue
        challenged[link.finding_id].append(
            FindingLine(
                id=str(line.id),
                section=line.section,
                title=line.title,
                effort_hours=float(line.effort_hours),
            )
        )
    ranked = sorted(findings, key=lambda f: (severity_rank(f.severity), f.position))
    counts = severity_counts(Severity(f.severity) for f in findings)
    return RedTeamReviewView(
        id=str(record.id),
        version=record.version,
        status=ReviewStatus(record.status),
        estimate_version_id=None
        if record.estimate_version_id is None
        else str(record.estimate_version_id),
        estimate_version=None if estimate is None else estimate.version,
        dropped_count=record.dropped_count,
        created_at=record.created_at,
        counts=SeverityCounts(
            critical=counts[Severity.CRITICAL],
            high=counts[Severity.HIGH],
            medium=counts[Severity.MEDIUM],
            low=counts[Severity.LOW],
        ),
        findings=[
            RedTeamFinding(
                id=str(f.id),
                position=f.position,
                category=FindingCategory(f.category),
                severity=Severity(f.severity),
                title=f.title,
                argument=f.argument,
                requirements=cited.get(f.id, []),
                lines=challenged.get(f.id, []),
            )
            for f in ranked
        ],
    )


async def get_red_team(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> RedTeamView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record = await repo.current_review(uow, opportunity_id, _KIND)
    return RedTeamView(
        review=None if record is None else await review_view(uow, record),
        run=_run(await repo.latest_run(uow, opportunity_id)),
        can_start=identity.can(actor, Action.RED_TEAM_START, resource),
    )


async def start_review(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> RedTeamRun:
    """Queue a new Red Team run of the Opportunity (the Retry of a failed one)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.RED_TEAM_START, resource)
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    busy = await repo.run_in(uow, opportunity_id, tuple(s.value for s in IN_PROGRESS))
    if busy is not None:
        raise RedTeamReviewInProgressError(IN_PROGRESS_DETAIL)
    run_id = await queue_review(uow, opportunity_id)
    _log.info(
        "assessments.red_team_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "actor_id": actor.actor.id,
        },
    )
    return RedTeamRun(status=RunStatus.QUEUED, error_code=None)
