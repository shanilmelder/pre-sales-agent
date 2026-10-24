"""Persistence for Red Team runs, Reviews, their Findings and the Findings' Requirement and
Estimate line links (Story 6.5), and (Story 6.4) the Critic's Finding targets: the specialist
Findings a Critic Finding cites, at their Assessment version. Runs inside the caller's Unit
of Work."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update

from app.modules.assessments.adapters.models import (
    FindingLineRow,
    FindingRequirementRow,
    FindingRow,
    FindingTargetRow,
    RedTeamRunRow,
    ReviewRow,
)
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    id: UUID
    opportunity_id: UUID
    kind: str
    version: int
    estimate_version_id: UUID | None
    status: str
    dropped_count: int
    created_at: datetime
    run_id: UUID | None = None
    """The assessment run a Critic Review reviewed (Story 6.4); None for a Red Team Review."""


@dataclass(frozen=True, slots=True)
class FindingRecord:
    id: UUID
    position: int
    category: str
    severity: str
    title: str
    argument: str


@dataclass(frozen=True, slots=True)
class FindingRequirementRecord:
    finding_id: UUID
    requirement_id: UUID
    requirement_version: int


@dataclass(frozen=True, slots=True)
class FindingLineRecord:
    finding_id: UUID
    line_id: UUID


@dataclass(frozen=True, slots=True)
class FindingTargetRecord:
    """A Critic Finding cites a specialist Finding at its Assessment's version."""

    finding_id: UUID
    assessment_finding_id: UUID
    assessment_id: UUID
    assessment_version: int


@dataclass(frozen=True, slots=True)
class NewFinding:
    finding_id: UUID
    position: int
    category: str
    severity: str
    title: str
    argument: str
    requirements: list[tuple[UUID, int]]
    lines: list[UUID]
    targets: list[tuple[UUID, UUID, int]] = field(default_factory=list)
    """Specialist Findings cited (Story 6.4): (Finding id, Assessment id, Assessment
    version)."""


# --- runs -----------------------------------------------------------------------------------


async def lock_reviews(uow: UnitOfWork, opportunity_id: UUID, kind: str) -> None:
    """Serialise accepting the Opportunity's Reviews of `kind` until commit (which numbers
    and supersedes them). The Red Team uses `lock_opportunity`, which also covers its runs."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.review:{kind}:{opportunity_id}"},
    )


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise the Opportunity's Red Team reviewing until commit: queueing, a job starting,
    and accepting a result (which numbers and supersedes Reviews)."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.red_team:{opportunity_id}"},
    )


def _run(row: RedTeamRunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        error_code=row.error_code,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def insert_run(uow: UnitOfWork, *, run_id: UUID, opportunity_id: UUID) -> None:
    await uow.session.execute(
        insert(RedTeamRunRow).values(id=run_id, opportunity_id=opportunity_id, status="queued")
    )


async def get_run(uow: UnitOfWork, run_id: UUID, *, for_update: bool = False) -> RunRecord | None:
    statement = (
        select(RedTeamRunRow)
        .where(RedTeamRunRow.id == run_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _run(row)


async def latest_run(uow: UnitOfWork, opportunity_id: UUID) -> RunRecord | None:
    row = (
        await uow.session.execute(
            select(RedTeamRunRow)
            .where(RedTeamRunRow.opportunity_id == opportunity_id)
            .order_by(RedTeamRunRow.created_at.desc(), RedTeamRunRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _run(row)


async def run_in(uow: UnitOfWork, opportunity_id: UUID, statuses: tuple[str, ...]) -> UUID | None:
    """A run of the Opportunity in one of `statuses` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(RedTeamRunRow.id)
            .where(
                RedTeamRunRow.opportunity_id == opportunity_id,
                RedTeamRunRow.status.in_(statuses),
            )
            .order_by(RedTeamRunRow.created_at, RedTeamRunRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def newer_succeeded(uow: UnitOfWork, record: RunRecord) -> bool:
    """Whether a run of the same Opportunity queued after this one has succeeded."""
    newer = await uow.session.execute(
        select(RedTeamRunRow.id)
        .where(
            RedTeamRunRow.opportunity_id == record.opportunity_id,
            RedTeamRunRow.status == "succeeded",
            tuple_(RedTeamRunRow.created_at, RedTeamRunRow.id) > (record.created_at, record.id),
        )
        .limit(1)
    )
    return newer.first() is not None


async def fail_stale_runs(
    uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta, error_code: str
) -> int:
    """Mark the Opportunity's runs still `queued` or `running` after `older_than` `failed`
    with `error_code`. Returns how many changed."""
    result = await uow.session.execute(
        update(RedTeamRunRow)
        .where(
            RedTeamRunRow.opportunity_id == opportunity_id,
            RedTeamRunRow.status.in_(("queued", "running")),
            RedTeamRunRow.created_at < func.now() - older_than,
        )
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(RedTeamRunRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def update_run(
    uow: UnitOfWork,
    run_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    finished: bool = False,
) -> bool:
    """Move the run to `status` if it is in one of `from_statuses`. False (and no change)
    otherwise."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    if finished:
        values["finished_at"] = func.now()
    result = await uow.session.execute(
        update(RedTeamRunRow)
        .where(RedTeamRunRow.id == run_id, RedTeamRunRow.status.in_(from_statuses))
        .values(**values)
        .returning(RedTeamRunRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Reviews --------------------------------------------------------------------------------


def _review(row: ReviewRow) -> ReviewRecord:
    return ReviewRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        kind=row.kind,
        version=row.version,
        estimate_version_id=row.estimate_version_id,
        status=row.status,
        dropped_count=row.dropped_count,
        created_at=row.created_at,
        run_id=row.run_id,
    )


async def latest_review_number(uow: UnitOfWork, opportunity_id: UUID, kind: str) -> int:
    """The Opportunity's highest Review version of `kind`, 0 before the first."""
    found = (
        await uow.session.execute(
            select(func.max(ReviewRow.version)).where(
                ReviewRow.opportunity_id == opportunity_id, ReviewRow.kind == kind
            )
        )
    ).scalar_one_or_none()
    return found or 0


async def supersede_reviews(uow: UnitOfWork, opportunity_id: UUID, kind: str) -> int:
    """Mark the Opportunity's `current` Review of `kind` `superseded`. Returns how many
    changed."""
    result = await uow.session.execute(
        update(ReviewRow)
        .where(
            ReviewRow.opportunity_id == opportunity_id,
            ReviewRow.kind == kind,
            ReviewRow.status == "current",
        )
        .values(status="superseded")
        .returning(ReviewRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def insert_review(
    uow: UnitOfWork,
    *,
    review_id: UUID,
    opportunity_id: UUID,
    kind: str,
    version: int,
    estimate_version_id: UUID | None,
    dropped_count: int,
    findings: list[NewFinding],
    run_id: UUID | None = None,
) -> None:
    """A `current` Review with its Findings and their Requirement, line and (Story 6.4)
    target links."""
    await uow.session.execute(
        insert(ReviewRow).values(
            id=review_id,
            opportunity_id=opportunity_id,
            kind=kind,
            version=version,
            estimate_version_id=estimate_version_id,
            status="current",
            dropped_count=dropped_count,
            run_id=run_id,
        )
    )
    if not findings:
        return
    await uow.session.execute(
        insert(FindingRow),
        [
            {
                "id": f.finding_id,
                "review_id": review_id,
                "position": f.position,
                "category": f.category,
                "severity": f.severity,
                "title": f.title,
                "argument": f.argument,
            }
            for f in findings
        ],
    )
    requirement_links = [
        {"finding_id": f.finding_id, "requirement_id": rid, "requirement_version": at}
        for f in findings
        for rid, at in f.requirements
    ]
    if requirement_links:
        await uow.session.execute(insert(FindingRequirementRow), requirement_links)
    target_links = [
        {
            "finding_id": f.finding_id,
            "assessment_finding_id": target,
            "assessment_id": assessment_id,
            "assessment_version": version,
        }
        for f in findings
        for target, assessment_id, version in f.targets
    ]
    if target_links:
        await uow.session.execute(insert(FindingTargetRow), target_links)
    line_links = [
        {"finding_id": f.finding_id, "line_id": line_id} for f in findings for line_id in f.lines
    ]
    if line_links:
        await uow.session.execute(insert(FindingLineRow), line_links)


async def current_review(uow: UnitOfWork, opportunity_id: UUID, kind: str) -> ReviewRecord | None:
    """The Opportunity's `current` Review of `kind`, if any (superseded ones are hidden)."""
    row = (
        await uow.session.execute(
            select(ReviewRow)
            .where(
                ReviewRow.opportunity_id == opportunity_id,
                ReviewRow.kind == kind,
                ReviewRow.status == "current",
            )
            .order_by(ReviewRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _review(row)


async def findings_of(uow: UnitOfWork, review_id: UUID) -> list[FindingRecord]:
    rows = await uow.session.execute(
        select(FindingRow).where(FindingRow.review_id == review_id).order_by(FindingRow.position)
    )
    return [
        FindingRecord(
            id=row.id,
            position=row.position,
            category=row.category,
            severity=row.severity,
            title=row.title,
            argument=row.argument,
        )
        for row in rows.scalars()
    ]


async def requirement_links_for(
    uow: UnitOfWork, finding_ids: list[UUID]
) -> list[FindingRequirementRecord]:
    if not finding_ids:
        return []
    rows = await uow.session.execute(
        select(FindingRequirementRow).where(FindingRequirementRow.finding_id.in_(finding_ids))
    )
    return [
        FindingRequirementRecord(
            finding_id=row.finding_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
        )
        for row in rows.scalars()
    ]


async def line_links_for(uow: UnitOfWork, finding_ids: list[UUID]) -> list[FindingLineRecord]:
    if not finding_ids:
        return []
    rows = await uow.session.execute(
        select(FindingLineRow).where(FindingLineRow.finding_id.in_(finding_ids))
    )
    return [
        FindingLineRecord(finding_id=row.finding_id, line_id=row.line_id) for row in rows.scalars()
    ]


async def target_links_for(uow: UnitOfWork, finding_ids: list[UUID]) -> list[FindingTargetRecord]:
    """The specialist Findings these Critic Findings cite (Story 6.4)."""
    if not finding_ids:
        return []
    rows = await uow.session.execute(
        select(FindingTargetRow).where(FindingTargetRow.finding_id.in_(finding_ids))
    )
    return [
        FindingTargetRecord(
            finding_id=row.finding_id,
            assessment_finding_id=row.assessment_finding_id,
            assessment_id=row.assessment_id,
            assessment_version=row.assessment_version,
        )
        for row in rows.scalars()
    ]
