"""Persistence for Red Team runs, Reviews, their Findings and the Findings' Requirement and
Estimate line links (Story 6.5), and (Story 6.4) the Critic's Finding targets: the specialist
Findings a Critic Finding cites, at their Assessment version. Runs inside the caller's Unit
of Work."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update

from app.modules.assessments.adapters.models import (
    FindingEvidenceRow,
    FindingLineRow,
    FindingOverrideRow,
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
    status: str = "open"
    fingerprint: str = ""
    security_discipline: bool = False
    policy_ref: dict[str, Any] | None = None
    previous_override_id: UUID | None = None
    resolution: dict[str, Any] | None = None
    row_version: int = 1
    review_id: UUID | None = None


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
    fingerprint: str = ""
    security_discipline: bool = False
    policy_ref: dict[str, Any] | None = None
    previous_override_id: UUID | None = None
    """Story 6.6: set at acceptance by code (`application/findings.py`)."""


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
                "fingerprint": f.fingerprint,
                "security_discipline": f.security_discipline,
                "policy_ref": f.policy_ref,
                "previous_override_id": f.previous_override_id,
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


def _finding(row: FindingRow) -> FindingRecord:
    return FindingRecord(
        id=row.id,
        position=row.position,
        category=row.category,
        severity=row.severity,
        title=row.title,
        argument=row.argument,
        status=row.status,
        fingerprint=row.fingerprint,
        security_discipline=row.security_discipline,
        policy_ref=row.policy_ref,
        previous_override_id=row.previous_override_id,
        resolution=row.resolution,
        row_version=row.row_version,
        review_id=row.review_id,
    )


async def findings_of(uow: UnitOfWork, review_id: UUID) -> list[FindingRecord]:
    rows = await uow.session.execute(
        select(FindingRow)
        .where(FindingRow.review_id == review_id)
        .order_by(FindingRow.position)
        .execution_options(populate_existing=True)
    )
    return [_finding(row) for row in rows.scalars()]


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


# --- blocking Findings and overrides (Story 6.6) --------------------------------------------


async def lock_findings(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise the Opportunity's Finding overrides and resolutions, and the carry-over of
    overrides at acceptance, until commit."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.findings:{opportunity_id}"},
    )


async def get_finding(
    uow: UnitOfWork, finding_id: UUID
) -> tuple[FindingRecord, ReviewRecord] | None:
    """The Finding and its Review, read afresh."""
    row = (
        await uow.session.execute(
            select(FindingRow, ReviewRow)
            .join(ReviewRow, ReviewRow.id == FindingRow.review_id)
            .where(FindingRow.id == finding_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    return None if row is None else (_finding(row[0]), _review(row[1]))


async def set_status(
    uow: UnitOfWork,
    finding_id: UUID,
    *,
    expected_row_version: int,
    status: str,
    resolution: dict[str, Any] | None,
) -> int | None:
    """Move an `open` Finding at `expected_row_version` to `status`; its new row version, or
    None (and no change) when it was not open at that version."""
    result = await uow.session.execute(
        update(FindingRow)
        .where(
            FindingRow.id == finding_id,
            FindingRow.status == "open",
            FindingRow.row_version == expected_row_version,
        )
        .values(status=status, resolution=resolution, row_version=FindingRow.row_version + 1)
        .returning(FindingRow.row_version)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class OverrideRecord:
    id: UUID
    finding_id: UUID
    review_kind: str
    review_version: int
    overridden_by: UUID
    reason: str
    policy_basis: str
    created_at: datetime


def _override(row: FindingOverrideRow) -> OverrideRecord:
    return OverrideRecord(
        id=row.id,
        finding_id=row.finding_id,
        review_kind=row.review_kind,
        review_version=row.review_version,
        overridden_by=row.overridden_by,
        reason=row.reason,
        policy_basis=row.policy_basis,
        created_at=row.created_at,
    )


async def insert_override(
    uow: UnitOfWork,
    *,
    override_id: UUID,
    finding_id: UUID,
    review_kind: str,
    review_version: int,
    overridden_by: UUID,
    reason: str,
    policy_basis: str,
) -> None:
    await uow.session.execute(
        insert(FindingOverrideRow).values(
            id=override_id,
            finding_id=finding_id,
            review_kind=review_kind,
            review_version=review_version,
            overridden_by=overridden_by,
            reason=reason,
            policy_basis=policy_basis,
        )
    )


async def overrides_by_id(uow: UnitOfWork, ids: list[UUID]) -> dict[UUID, OverrideRecord]:
    if not ids:
        return {}
    rows = await uow.session.execute(
        select(FindingOverrideRow).where(FindingOverrideRow.id.in_(ids))
    )
    return {row.id: _override(row) for row in rows.scalars()}


async def overrides_for(uow: UnitOfWork, finding_ids: list[UUID]) -> dict[UUID, OverrideRecord]:
    """The override of each of these Findings that has one (a Finding is overridden once)."""
    if not finding_ids:
        return {}
    rows = await uow.session.execute(
        select(FindingOverrideRow)
        .where(FindingOverrideRow.finding_id.in_(finding_ids))
        .order_by(FindingOverrideRow.created_at)
    )
    return {row.finding_id: _override(row) for row in rows.scalars()}


async def latest_overrides(
    uow: UnitOfWork, opportunity_id: UUID, kind: str, before_version: int, fingerprints: list[str]
) -> dict[str, UUID]:
    """`{fingerprint: override id}`: for each fingerprint, the newest override of a Finding
    with it in one of the Opportunity's Reviews of `kind` older than `before_version`."""
    if not fingerprints:
        return {}
    rows = await uow.session.execute(
        select(FindingRow.fingerprint, FindingOverrideRow.id)
        .join(FindingOverrideRow, FindingOverrideRow.finding_id == FindingRow.id)
        .join(ReviewRow, ReviewRow.id == FindingRow.review_id)
        .where(
            ReviewRow.opportunity_id == opportunity_id,
            ReviewRow.kind == kind,
            ReviewRow.version < before_version,
            FindingRow.fingerprint.in_(fingerprints),
        )
        .order_by(ReviewRow.version, FindingOverrideRow.created_at)
    )
    return {fp: override_id for fp, override_id in rows.all()}


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    finding_id: UUID
    position: int
    kind: str
    ref_id: UUID
    ref_version: int


async def insert_evidence(
    uow: UnitOfWork, finding_id: UUID, refs: list[tuple[str, UUID, int]]
) -> None:
    if not refs:
        return
    await uow.session.execute(
        insert(FindingEvidenceRow),
        [
            {
                "finding_id": finding_id,
                "position": position,
                "kind": kind,
                "ref_id": ref_id,
                "ref_version": version,
            }
            for position, (kind, ref_id, version) in enumerate(refs, start=1)
        ],
    )


async def evidence_for(uow: UnitOfWork, finding_ids: list[UUID]) -> list[EvidenceRecord]:
    if not finding_ids:
        return []
    rows = await uow.session.execute(
        select(FindingEvidenceRow)
        .where(FindingEvidenceRow.finding_id.in_(finding_ids))
        .order_by(FindingEvidenceRow.finding_id, FindingEvidenceRow.position)
    )
    return [
        EvidenceRecord(
            finding_id=row.finding_id,
            position=row.position,
            kind=row.kind,
            ref_id=row.ref_id,
            ref_version=row.ref_version,
        )
        for row in rows.scalars()
    ]


@dataclass(frozen=True, slots=True)
class BlockingRecord:
    finding_id: UUID
    review_kind: str
    review_version: int
    title: str = field(repr=False)


async def blocking_findings(uow: UnitOfWork, opportunity_id: UUID) -> list[BlockingRecord]:
    """The `open`, `critical` Findings of the Opportunity's current Critic and Red Team
    Reviews, by kind and position."""
    rows = await uow.session.execute(
        select(FindingRow.id, ReviewRow.kind, ReviewRow.version, FindingRow.title)
        .join(ReviewRow, ReviewRow.id == FindingRow.review_id)
        .where(
            ReviewRow.opportunity_id == opportunity_id,
            ReviewRow.status == "current",
            FindingRow.status == "open",
            FindingRow.severity == "critical",
        )
        .order_by(ReviewRow.kind, FindingRow.position)
    )
    return [
        BlockingRecord(finding_id=i, review_kind=k, review_version=v, title=t)
        for i, k, v, t in rows.all()
    ]
