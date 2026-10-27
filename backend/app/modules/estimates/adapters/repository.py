"""Persistence for drafts, Estimate Versions, their lines and the lines' Requirement links
(Story 8.1), Assumptions (Story 8.4; carried to a re-draft, Story 8.7; edited, Story 8.5)
and Risks (Story 8.5). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, tuple_, update

from app.modules.estimates.adapters.models import (
    AssumptionRow,
    BaselineRow,
    DraftRow,
    EstimateLineRow,
    EstimateVersionRow,
    LineRequirementRow,
    RiskRow,
)
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class DraftRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    requested_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    id: UUID
    opportunity_id: UUID
    version: int
    status: str
    template_version: str
    uncovered_count: int
    dropped_count: int
    row_version: int
    created_at: datetime
    proposal_status: str | None = None
    uncarried_edit_count: int = 0
    source: str = "model"
    source_run_id: UUID | None = None
    submitted_at: datetime | None = None
    created_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class LineRecord:
    id: UUID
    position: int
    section: str
    title: str
    effort_hours: Decimal
    role_mix: dict[str, Any]
    basis: str
    version_id: UUID | None = None
    row_version: int = 1
    edited_by: UUID | None = None
    edited_at: datetime | None = None
    edit_reason: str | None = None
    edit_carried_from_version: int | None = None


@dataclass(frozen=True, slots=True)
class LineLinkRecord:
    line_id: UUID
    requirement_id: UUID
    requirement_version: int


@dataclass(frozen=True, slots=True)
class NewLine:
    line_id: UUID
    position: int
    section: str
    title: str
    effort_hours: Decimal
    role_mix: dict[str, int]
    basis: str
    requirements: list[tuple[UUID, int]]


# --- drafts ---------------------------------------------------------------------------------


def _draft(row: DraftRow) -> DraftRecord:
    return DraftRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        error_code=row.error_code,
        created_at=row.created_at,
        finished_at=row.finished_at,
        requested_by=row.requested_by,
    )


async def insert_draft(
    uow: UnitOfWork, *, draft_id: UUID, opportunity_id: UUID, requested_by: UUID | None = None
) -> None:
    await uow.session.execute(
        insert(DraftRow).values(
            id=draft_id, opportunity_id=opportunity_id, status="queued", requested_by=requested_by
        )
    )


async def get_draft(
    uow: UnitOfWork, draft_id: UUID, *, for_update: bool = False
) -> DraftRecord | None:
    statement = select(DraftRow).where(DraftRow.id == draft_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _draft(row)


async def latest_draft(uow: UnitOfWork, opportunity_id: UUID) -> DraftRecord | None:
    row = (
        await uow.session.execute(
            select(DraftRow)
            .where(DraftRow.opportunity_id == opportunity_id)
            .order_by(DraftRow.created_at.desc(), DraftRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _draft(row)


async def draft_in(uow: UnitOfWork, opportunity_id: UUID, statuses: tuple[str, ...]) -> UUID | None:
    """A draft of the Opportunity in one of `statuses` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(DraftRow.id)
            .where(DraftRow.opportunity_id == opportunity_id, DraftRow.status.in_(statuses))
            .order_by(DraftRow.created_at, DraftRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def newer_succeeded(uow: UnitOfWork, record: DraftRecord) -> bool:
    """Whether a draft of the same Opportunity queued after this one has succeeded."""
    newer = await uow.session.execute(
        select(DraftRow.id)
        .where(
            DraftRow.opportunity_id == record.opportunity_id,
            DraftRow.status == "succeeded",
            tuple_(DraftRow.created_at, DraftRow.id) > (record.created_at, record.id),
        )
        .limit(1)
    )
    return newer.first() is not None


async def fail_stale_drafts(
    uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta, error_code: str
) -> int:
    """Mark the Opportunity's drafts still `queued` or `running` after `older_than` `failed`
    with `error_code`. Returns how many changed."""
    result = await uow.session.execute(
        update(DraftRow)
        .where(
            DraftRow.opportunity_id == opportunity_id,
            DraftRow.status.in_(("queued", "running")),
            DraftRow.created_at < func.now() - older_than,
        )
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(DraftRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def update_draft(
    uow: UnitOfWork,
    draft_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    finished: bool = False,
) -> bool:
    """Move the draft to `status` if it is in one of `from_statuses`. False (and no change)
    otherwise."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    if finished:
        values["finished_at"] = func.now()
    result = await uow.session.execute(
        update(DraftRow)
        .where(DraftRow.id == draft_id, DraftRow.status.in_(from_statuses))
        .values(**values)
        .returning(DraftRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Estimate Versions ----------------------------------------------------------------------


def _version(row: EstimateVersionRow) -> VersionRecord:
    return VersionRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        version=row.version,
        status=row.status,
        template_version=row.template_version,
        uncovered_count=row.uncovered_count,
        dropped_count=row.dropped_count,
        row_version=row.row_version,
        created_at=row.created_at,
        proposal_status=row.proposal_status,
        uncarried_edit_count=row.uncarried_edit_count,
        source=row.source,
        source_run_id=row.source_run_id,
        submitted_at=row.submitted_at,
        created_by=row.created_by,
    )


async def latest_version_number(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """The Opportunity's highest version number, 0 before the first."""
    found = (
        await uow.session.execute(
            select(func.max(EstimateVersionRow.version)).where(
                EstimateVersionRow.opportunity_id == opportunity_id
            )
        )
    ).scalar_one_or_none()
    return found or 0


async def first_submitted_after(uow: UnitOfWork, opportunity_id: UUID, version: int) -> int | None:
    """Story 9.4: the number of the Opportunity's first version after `version` that was
    submitted (the one that superseded a submitted version), or None."""
    found = await uow.session.execute(
        select(func.min(EstimateVersionRow.version)).where(
            EstimateVersionRow.opportunity_id == opportunity_id,
            EstimateVersionRow.version > version,
            EstimateVersionRow.submitted_at.is_not(None),
        )
    )
    return found.scalar_one_or_none()


async def supersede_drafts(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """Mark the Opportunity's `draft` version `superseded`. Returns how many changed."""
    result = await uow.session.execute(
        update(EstimateVersionRow)
        .where(
            EstimateVersionRow.opportunity_id == opportunity_id,
            EstimateVersionRow.status == "draft",
        )
        .values(status="superseded", row_version=EstimateVersionRow.row_version + 1)
        .returning(EstimateVersionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def insert_version(
    uow: UnitOfWork,
    *,
    version_id: UUID,
    opportunity_id: UUID,
    version: int,
    template_version: str,
    uncovered_count: int,
    dropped_count: int,
    lines: list[NewLine],
    proposal_status: str | None = None,
    source: str = "model",
    source_run_id: UUID | None = None,
    created_by: UUID | None = None,
) -> None:
    """A `draft` Estimate Version with its lines and their Requirement links. `created_by`
    (Story 9.1): the person who triggered it, if known."""
    await uow.session.execute(
        insert(EstimateVersionRow).values(
            id=version_id,
            opportunity_id=opportunity_id,
            version=version,
            status="draft",
            template_version=template_version,
            uncovered_count=uncovered_count,
            dropped_count=dropped_count,
            proposal_status=proposal_status,
            source=source,
            source_run_id=source_run_id,
            created_by=created_by,
            row_version=1,
        )
    )
    if not lines:
        return
    await uow.session.execute(
        insert(EstimateLineRow),
        [
            {
                "id": line.line_id,
                "version_id": version_id,
                "position": line.position,
                "section": line.section,
                "title": line.title,
                "effort_hours": line.effort_hours,
                "role_mix": line.role_mix,
                "basis": line.basis,
            }
            for line in lines
        ],
    )
    links = [
        {"line_id": line.line_id, "requirement_id": rid, "requirement_version": version}
        for line in lines
        for rid, version in line.requirements
    ]
    if links:  # Story 9.4: a copied line may cover nothing
        await uow.session.execute(insert(LineRequirementRow), links)


async def has_version_from(uow: UnitOfWork, opportunity_id: UUID, source: str) -> bool:
    """Whether any Estimate Version of the Opportunity, whatever its status, came from
    `source` (Story 8.3)."""
    found = await uow.session.execute(
        select(EstimateVersionRow.id)
        .where(
            EstimateVersionRow.opportunity_id == opportunity_id,
            EstimateVersionRow.source == source,
        )
        .limit(1)
    )
    return found.first() is not None


_SENT_STATUSES = ("submitted", "in_review", "approved", "rejected")
_CURRENT_STATUSES = ("draft", *_SENT_STATUSES)


def _current_first(rows: list[EstimateVersionRow]) -> EstimateVersionRow | None:
    """The draft among these versions of one Opportunity, else the latest `submitted`,
    `in_review` (Story 9.1), `approved` or `rejected` (Story 9.3) one."""
    drafts = [r for r in rows if r.status == "draft"]
    pool = drafts or [r for r in rows if r.status in _SENT_STATUSES]
    return max(pool, key=lambda r: r.version, default=None)


async def current_version(uow: UnitOfWork, opportunity_id: UUID) -> VersionRecord | None:
    """The Opportunity's current Estimate Version: its `draft` if it has one, otherwise its
    latest `submitted` (Story 8.6), `in_review` (Story 9.1), `approved` or `rejected` (Story
    9.3) version; superseded versions never are."""
    rows = await uow.session.execute(
        select(EstimateVersionRow)
        .where(
            EstimateVersionRow.opportunity_id == opportunity_id,
            EstimateVersionRow.status.in_(_CURRENT_STATUSES),
        )
        .execution_options(populate_existing=True)
    )
    found = _current_first(list(rows.scalars()))
    return None if found is None else _version(found)


async def draft_version(uow: UnitOfWork, opportunity_id: UUID) -> VersionRecord | None:
    """The Opportunity's `draft` version, if any (never a submitted one)."""
    found = await current_version(uow, opportunity_id)
    return found if found is not None and found.status == "draft" else None


async def current_versions(
    uow: UnitOfWork, opportunity_ids: list[UUID]
) -> dict[UUID, VersionRecord]:
    """Each of these Opportunities' current version (as `current_version`), in one query;
    ones with none are left out."""
    if not opportunity_ids:
        return {}
    rows = await uow.session.execute(
        select(EstimateVersionRow).where(
            EstimateVersionRow.opportunity_id.in_(opportunity_ids),
            EstimateVersionRow.status.in_(_CURRENT_STATUSES),
        )
    )
    by_opportunity: dict[UUID, list[EstimateVersionRow]] = {}
    for row in rows.scalars():
        by_opportunity.setdefault(row.opportunity_id, []).append(row)
    found: dict[UUID, VersionRecord] = {}
    for opportunity_id, candidates in by_opportunity.items():
        current = _current_first(candidates)
        if current is not None:
            found[opportunity_id] = _version(current)
    return found


async def submit_version(
    uow: UnitOfWork, version_id: UUID, *, expected_row_version: int
) -> VersionRecord | None:
    """Move the `draft` version at `expected_row_version` to `submitted`, bumping its
    `row_version`. None (and no change) when it is not a draft at that row version."""
    changed = (
        await uow.session.execute(
            update(EstimateVersionRow)
            .where(
                EstimateVersionRow.id == version_id,
                EstimateVersionRow.status == "draft",
                EstimateVersionRow.row_version == expected_row_version,
            )
            .values(
                status="submitted",
                submitted_at=func.now(),
                row_version=EstimateVersionRow.row_version + 1,
            )
            .returning(EstimateVersionRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_version(uow, version_id)


async def move_status(
    uow: UnitOfWork, version_id: UUID, *, from_status: str, to_status: str
) -> VersionRecord | None:
    """Story 9.1: move the version from `from_status` to `to_status` (`submitted`,
    `in_review`, and Story 9.3's `approved` and `rejected`), bumping its `row_version`; None
    (and no change) when it is not in `from_status`."""
    changed = (
        await uow.session.execute(
            update(EstimateVersionRow)
            .where(EstimateVersionRow.id == version_id, EstimateVersionRow.status == from_status)
            .values(status=to_status, row_version=EstimateVersionRow.row_version + 1)
            .returning(EstimateVersionRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_version(uow, version_id)


async def supersede_submitted(
    uow: UnitOfWork, opportunity_id: UUID, *, keep: UUID
) -> list[VersionRecord]:
    """Mark the Opportunity's `submitted`, `in_review` (Story 9.1), `approved` and `rejected`
    (Story 9.3) versions other than `keep` `superseded` (bumping their `row_version`); the
    versions as they are now, oldest first. Story 9.7: the current Baseline's version is never
    superseded (it stays `approved`)."""
    conditions = [
        EstimateVersionRow.opportunity_id == opportunity_id,
        EstimateVersionRow.status.in_(_SENT_STATUSES),
        EstimateVersionRow.id != keep,
    ]
    baseline = await current_baseline(uow, opportunity_id)
    if baseline is not None:
        conditions.append(EstimateVersionRow.id != baseline.estimate_version_id)
    result = await uow.session.execute(
        update(EstimateVersionRow)
        .where(*conditions)
        .values(status="superseded", row_version=EstimateVersionRow.row_version + 1)
        .returning(EstimateVersionRow.id)
        .execution_options(synchronize_session=False)
    )
    ids = [row.id for row in result.all()]
    found = [v for i in ids if (v := await get_version(uow, i)) is not None]
    return sorted(found, key=lambda v: v.version)


async def covered_requirement_ids(
    uow: UnitOfWork, version_ids: list[UUID]
) -> dict[UUID, set[UUID]]:
    """The Requirements some line of each version covers, by version, in one query."""
    found: dict[UUID, set[UUID]] = {v: set() for v in version_ids}
    if not version_ids:
        return found
    rows = await uow.session.execute(
        select(EstimateLineRow.version_id, LineRequirementRow.requirement_id)
        .join(LineRequirementRow, LineRequirementRow.line_id == EstimateLineRow.id)
        .where(EstimateLineRow.version_id.in_(version_ids))
    )
    for version_id, requirement_id in rows.all():
        found[version_id].add(requirement_id)
    return found


async def unaccepted_counts(uow: UnitOfWork, version_ids: list[UUID]) -> dict[UUID, int]:
    """How many unaccepted Assumptions each version has, in one query; none counts 0."""
    found: dict[UUID, int] = {v: 0 for v in version_ids}
    if not version_ids:
        return found
    rows = await uow.session.execute(
        select(AssumptionRow.version_id, func.count())
        .where(AssumptionRow.version_id.in_(version_ids), AssumptionRow.accepted_at.is_(None))
        .group_by(AssumptionRow.version_id)
    )
    for version_id, count in rows.all():
        found[version_id] = int(count)
    return found


def _line(row: EstimateLineRow) -> LineRecord:
    return LineRecord(
        id=row.id,
        position=row.position,
        section=row.section,
        title=row.title,
        effort_hours=row.effort_hours,
        role_mix=row.role_mix,
        basis=row.basis,
        version_id=row.version_id,
        row_version=row.row_version,
        edited_by=row.edited_by,
        edited_at=row.edited_at,
        edit_reason=row.edit_reason,
        edit_carried_from_version=row.edit_carried_from_version,
    )


async def lines_of(uow: UnitOfWork, version_id: UUID) -> list[LineRecord]:
    rows = await uow.session.execute(
        select(EstimateLineRow)
        .where(EstimateLineRow.version_id == version_id)
        .order_by(EstimateLineRow.position)
        .execution_options(populate_existing=True)
    )
    return [_line(row) for row in rows.scalars()]


async def lines_of_versions(
    uow: UnitOfWork, version_ids: list[UUID]
) -> dict[UUID, list[LineRecord]]:
    """These versions' lines by version, each in order, in one query."""
    found: dict[UUID, list[LineRecord]] = {}
    if not version_ids:
        return found
    rows = await uow.session.execute(
        select(EstimateLineRow)
        .where(EstimateLineRow.version_id.in_(version_ids))
        .order_by(EstimateLineRow.version_id, EstimateLineRow.position)
        .execution_options(populate_existing=True)
    )
    for row in rows.scalars():
        found.setdefault(row.version_id, []).append(_line(row))
    return found


# --- line edits (Story 8.2) -----------------------------------------------------------------


async def get_line(uow: UnitOfWork, line_id: UUID) -> LineRecord | None:
    row = (
        await uow.session.execute(
            select(EstimateLineRow)
            .where(EstimateLineRow.id == line_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _line(row)


async def edit_line(
    uow: UnitOfWork,
    line_id: UUID,
    *,
    expected_row_version: int,
    effort_hours: Decimal,
    role_mix: dict[str, int],
    user_id: UUID,
    reason: str,
) -> LineRecord | None:
    """A person's edit of the line at `expected_row_version`: its effort and role mix, who,
    now, why; no longer carried. Bumps `row_version`. None (and no change) when the line is
    at another row version."""
    changed = (
        await uow.session.execute(
            update(EstimateLineRow)
            .where(
                EstimateLineRow.id == line_id,
                EstimateLineRow.row_version == expected_row_version,
            )
            .values(
                effort_hours=effort_hours,
                role_mix=role_mix,
                edited_by=user_id,
                edited_at=func.now(),
                edit_reason=reason,
                edit_carried_from_version=None,
                row_version=EstimateLineRow.row_version + 1,
            )
            .returning(EstimateLineRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_line(uow, line_id)


async def carry_line_edit(
    uow: UnitOfWork, line_id: UUID, *, source: LineRecord, from_version: int
) -> None:
    """Copy an edited line's hours, role mix, editor, time and reason onto a just-inserted
    line of the new draft, marked as carried from `from_version`. Its `row_version` stays 1:
    nobody has read it yet."""
    await uow.session.execute(
        update(EstimateLineRow)
        .where(EstimateLineRow.id == line_id)
        .values(
            effort_hours=source.effort_hours,
            role_mix=source.role_mix,
            edited_by=source.edited_by,
            edited_at=source.edited_at,
            edit_reason=source.edit_reason,
            edit_carried_from_version=from_version,
        )
        .execution_options(synchronize_session=False)
    )


async def set_uncarried_edit_count(uow: UnitOfWork, version_id: UUID, count: int) -> None:
    await uow.session.execute(
        update(EstimateVersionRow)
        .where(EstimateVersionRow.id == version_id)
        .values(uncarried_edit_count=count)
        .execution_options(synchronize_session=False)
    )


async def links_for(uow: UnitOfWork, line_ids: list[UUID]) -> list[LineLinkRecord]:
    if not line_ids:
        return []
    rows = await uow.session.execute(
        select(LineRequirementRow).where(LineRequirementRow.line_id.in_(line_ids))
    )
    return [
        LineLinkRecord(
            line_id=row.line_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
        )
        for row in rows.scalars()
    ]


async def version_by_number(
    uow: UnitOfWork, opportunity_id: UUID, number: int
) -> VersionRecord | None:
    """Story 9.3: the Opportunity's Estimate Version with this number, whatever its status."""
    row = (
        await uow.session.execute(
            select(EstimateVersionRow)
            .where(
                EstimateVersionRow.opportunity_id == opportunity_id,
                EstimateVersionRow.version == number,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _version(row)


async def get_version(
    uow: UnitOfWork, version_id: UUID, *, for_update: bool = False
) -> VersionRecord | None:
    statement = (
        select(EstimateVersionRow)
        .where(EstimateVersionRow.id == version_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _version(row)


async def set_proposal_status(
    uow: UnitOfWork, version_id: UUID, *, from_statuses: tuple[str, ...], status: str
) -> bool:
    """Move the version's `proposal_status` to `status` if it is in one of `from_statuses`.
    The version's `row_version` is left alone: the state of its proposals is not its content.
    False (and no change) otherwise."""
    result = await uow.session.execute(
        update(EstimateVersionRow)
        .where(
            EstimateVersionRow.id == version_id,
            EstimateVersionRow.proposal_status.in_(from_statuses),
        )
        .values(proposal_status=status)
        .returning(EstimateVersionRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Assumptions (Story 8.4) ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssumptionRecord:
    id: UUID
    version_id: UUID
    position: int
    kind: str
    wording: str
    amount_hours: Decimal | None
    line_id: UUID | None
    origin_ref: dict[str, Any]
    accepted_by: UUID | None
    accepted_at: datetime | None
    row_version: int
    created_at: datetime
    carried_from: UUID | None = None
    changed_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class NewAssumption:
    assumption_id: UUID
    position: int
    kind: str
    wording: str
    amount_hours: Decimal | None
    line_id: UUID | None
    origin_ref: dict[str, Any]


def _assumption(row: AssumptionRow) -> AssumptionRecord:
    return AssumptionRecord(
        id=row.id,
        version_id=row.version_id,
        position=row.position,
        kind=row.kind,
        wording=row.wording,
        amount_hours=row.amount_hours,
        line_id=row.line_id,
        origin_ref=row.origin_ref,
        accepted_by=row.accepted_by,
        accepted_at=row.accepted_at,
        row_version=row.row_version,
        created_at=row.created_at,
        carried_from=row.carried_from,
        changed_by=row.changed_by,
    )


async def has_proposed_assumptions(uow: UnitOfWork, version_id: UUID) -> bool:
    """Whether the version has an Assumption that was not carried from an earlier version
    (i.e. its proposals are stored already)."""
    found = await uow.session.execute(
        select(AssumptionRow.id)
        .where(AssumptionRow.version_id == version_id, AssumptionRow.carried_from.is_(None))
        .limit(1)
    )
    return found.first() is not None


async def last_assumption_position(uow: UnitOfWork, version_id: UUID) -> int:
    """The version's highest Assumption position, 0 when it has none."""
    found = (
        await uow.session.execute(
            select(func.max(AssumptionRow.position)).where(AssumptionRow.version_id == version_id)
        )
    ).scalar_one_or_none()
    return found or 0


@dataclass(frozen=True, slots=True)
class CarriedAssumption:
    """A copy of an accepted Assumption into a new version (Story 8.7)."""

    assumption_id: UUID
    position: int
    line_id: UUID | None
    source: AssumptionRecord


async def insert_carried_assumptions(
    uow: UnitOfWork, version_id: UUID, carried: list[CarriedAssumption]
) -> None:
    """Accepted copies of earlier Assumptions: same kind, wording, hours, origin and
    acceptance, a new id, `row_version` 1, and `carried_from` the source's id."""
    if not carried:
        return
    await uow.session.execute(
        insert(AssumptionRow),
        [
            {
                "id": c.assumption_id,
                "version_id": version_id,
                "position": c.position,
                "kind": c.source.kind,
                "wording": c.source.wording,
                "amount_hours": c.source.amount_hours,
                "line_id": c.line_id,
                "origin_ref": c.source.origin_ref,
                "accepted_by": c.source.accepted_by,
                "accepted_at": c.source.accepted_at,
                "carried_from": c.source.id,
                "changed_by": c.source.changed_by,
                "row_version": 1,
            }
            for c in carried
        ],
    )


async def carried_from_versions(uow: UnitOfWork, source_ids: list[UUID]) -> dict[UUID, int]:
    """`{source Assumption id: its version number}`."""
    if not source_ids:
        return {}
    rows = await uow.session.execute(
        select(AssumptionRow.id, EstimateVersionRow.version)
        .join(EstimateVersionRow, EstimateVersionRow.id == AssumptionRow.version_id)
        .where(AssumptionRow.id.in_(source_ids))
    )
    return {row.id: row.version for row in rows}


async def insert_assumptions(
    uow: UnitOfWork, version_id: UUID, assumptions: list[NewAssumption]
) -> None:
    """Unaccepted Assumptions of the version."""
    if not assumptions:
        return
    await uow.session.execute(
        insert(AssumptionRow),
        [
            {
                "id": a.assumption_id,
                "version_id": version_id,
                "position": a.position,
                "kind": a.kind,
                "wording": a.wording,
                "amount_hours": a.amount_hours,
                "line_id": a.line_id,
                "origin_ref": a.origin_ref,
                "row_version": 1,
            }
            for a in assumptions
        ],
    )


async def assumptions_of(
    uow: UnitOfWork,
    version_id: UUID,
    *,
    unaccepted_only: bool = False,
    accepted_only: bool = False,
) -> list[AssumptionRecord]:
    """The version's Assumptions in order (carried ones first, then the proposals)."""
    statement = (
        select(AssumptionRow)
        .where(AssumptionRow.version_id == version_id)
        .order_by(AssumptionRow.position)
        .execution_options(populate_existing=True)
    )
    if unaccepted_only:
        statement = statement.where(AssumptionRow.accepted_at.is_(None))
    if accepted_only:
        statement = statement.where(AssumptionRow.accepted_at.is_not(None))
    rows = await uow.session.execute(statement)
    return [_assumption(row) for row in rows.scalars()]


async def assumptions_of_versions(
    uow: UnitOfWork, version_ids: list[UUID]
) -> dict[UUID, list[AssumptionRecord]]:
    """These versions' Assumptions by version, each in order, in one query."""
    found: dict[UUID, list[AssumptionRecord]] = {}
    if not version_ids:
        return found
    rows = await uow.session.execute(
        select(AssumptionRow)
        .where(AssumptionRow.version_id.in_(version_ids))
        .order_by(AssumptionRow.version_id, AssumptionRow.position)
        .execution_options(populate_existing=True)
    )
    for row in rows.scalars():
        found.setdefault(row.version_id, []).append(_assumption(row))
    return found


async def get_assumption(uow: UnitOfWork, assumption_id: UUID) -> AssumptionRecord | None:
    row = (
        await uow.session.execute(
            select(AssumptionRow)
            .where(AssumptionRow.id == assumption_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _assumption(row)


async def accept_assumption(
    uow: UnitOfWork, assumption_id: UUID, *, expected_row_version: int, user_id: UUID
) -> AssumptionRecord | None:
    """Accept the unaccepted Assumption at `expected_row_version` as `user_id`, now. None (and
    no change) when it is accepted already or at another row version."""
    changed = (
        await uow.session.execute(
            update(AssumptionRow)
            .where(
                AssumptionRow.id == assumption_id,
                AssumptionRow.row_version == expected_row_version,
                AssumptionRow.accepted_at.is_(None),
            )
            .values(
                accepted_by=user_id,
                accepted_at=func.now(),
                changed_by=user_id,
                row_version=AssumptionRow.row_version + 1,
            )
            .returning(AssumptionRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_assumption(uow, assumption_id)


async def edit_assumption(
    uow: UnitOfWork,
    assumption_id: UUID,
    *,
    expected_row_version: int,
    kind: str,
    wording: str,
    amount_hours: Decimal | None,
    line_id: UUID | None,
    user_id: UUID,
) -> AssumptionRecord | None:
    """Story 8.5: a person's edit of the Assumption at `expected_row_version`: its kind,
    wording, hours and line, the acceptance cleared. Bumps `row_version`. None (and no
    change) when it is at another row version."""
    changed = (
        await uow.session.execute(
            update(AssumptionRow)
            .where(
                AssumptionRow.id == assumption_id,
                AssumptionRow.row_version == expected_row_version,
            )
            .values(
                kind=kind,
                wording=wording,
                amount_hours=amount_hours,
                line_id=line_id,
                accepted_by=None,
                accepted_at=None,
                changed_by=user_id,
                row_version=AssumptionRow.row_version + 1,
            )
            .returning(AssumptionRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_assumption(uow, assumption_id)


async def delete_unaccepted_for_gap(uow: UnitOfWork, version_id: UUID, gap_id: UUID) -> int:
    """Story 8.5: remove the version's unaccepted Assumptions made from `gap_id` (its Gap
    became a Risk). Returns how many."""
    result = await uow.session.execute(
        delete(AssumptionRow)
        .where(
            AssumptionRow.version_id == version_id,
            AssumptionRow.accepted_at.is_(None),
            AssumptionRow.origin_ref["id"].astext == str(gap_id),
        )
        .returning(AssumptionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


# --- Risks (Story 8.5) ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskRecord:
    id: UUID
    version_id: UUID
    position: int
    description: str
    likelihood: str
    impact: str
    origin_ref: dict[str, Any]
    created_by: UUID
    created_at: datetime
    row_version: int
    changed_by: UUID | None = None
    carried_from: UUID | None = None


def _risk(row: RiskRow) -> RiskRecord:
    return RiskRecord(
        id=row.id,
        version_id=row.version_id,
        position=row.position,
        description=row.description,
        likelihood=row.likelihood,
        impact=row.impact,
        origin_ref=row.origin_ref,
        created_by=row.created_by,
        created_at=row.created_at,
        row_version=row.row_version,
        changed_by=row.changed_by,
        carried_from=row.carried_from,
    )


async def last_risk_position(uow: UnitOfWork, version_id: UUID) -> int:
    """The version's highest Risk position, 0 when it has none."""
    found = (
        await uow.session.execute(
            select(func.max(RiskRow.position)).where(RiskRow.version_id == version_id)
        )
    ).scalar_one_or_none()
    return found or 0


async def insert_risk(
    uow: UnitOfWork,
    *,
    risk_id: UUID,
    version_id: UUID,
    position: int,
    description: str,
    likelihood: str,
    impact: str,
    origin_ref: dict[str, Any],
    user_id: UUID,
) -> RiskRecord:
    await uow.session.execute(
        insert(RiskRow).values(
            id=risk_id,
            version_id=version_id,
            position=position,
            description=description,
            likelihood=likelihood,
            impact=impact,
            origin_ref=origin_ref,
            created_by=user_id,
            changed_by=user_id,
            row_version=1,
        )
    )
    found = await get_risk(uow, risk_id)
    if found is None:  # pragma: no cover - just inserted
        raise RuntimeError("The Risk was not stored.")
    return found


async def get_risk(uow: UnitOfWork, risk_id: UUID) -> RiskRecord | None:
    row = (
        await uow.session.execute(
            select(RiskRow).where(RiskRow.id == risk_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _risk(row)


async def risks_of(uow: UnitOfWork, version_id: UUID) -> list[RiskRecord]:
    """The version's Risks in the order they were made (carried ones first)."""
    rows = await uow.session.execute(
        select(RiskRow)
        .where(RiskRow.version_id == version_id)
        .order_by(RiskRow.position)
        .execution_options(populate_existing=True)
    )
    return [_risk(row) for row in rows.scalars()]


async def edit_risk(
    uow: UnitOfWork,
    risk_id: UUID,
    *,
    expected_row_version: int,
    description: str,
    likelihood: str,
    impact: str,
    user_id: UUID,
) -> RiskRecord | None:
    """A person's edit of the Risk at `expected_row_version`. Bumps `row_version`. None (and
    no change) when it is at another row version."""
    changed = (
        await uow.session.execute(
            update(RiskRow)
            .where(RiskRow.id == risk_id, RiskRow.row_version == expected_row_version)
            .values(
                description=description,
                likelihood=likelihood,
                impact=impact,
                changed_by=user_id,
                row_version=RiskRow.row_version + 1,
            )
            .returning(RiskRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_risk(uow, risk_id)


@dataclass(frozen=True, slots=True)
class CarriedRisk:
    """A copy of a Risk into a new version (Story 8.5)."""

    risk_id: UUID
    position: int
    source: RiskRecord


async def insert_carried_risks(
    uow: UnitOfWork, version_id: UUID, carried: list[CarriedRisk]
) -> None:
    """Copies of earlier Risks: same description, levels, origin and creator, a new id,
    `row_version` 1, and `carried_from` the source's id."""
    if not carried:
        return
    await uow.session.execute(
        insert(RiskRow),
        [
            {
                "id": c.risk_id,
                "version_id": version_id,
                "position": c.position,
                "description": c.source.description,
                "likelihood": c.source.likelihood,
                "impact": c.source.impact,
                "origin_ref": c.source.origin_ref,
                "created_by": c.source.created_by,
                "created_at": c.source.created_at,
                "changed_by": c.source.changed_by,
                "carried_from": c.source.id,
                "row_version": 1,
            }
            for c in carried
        ],
    )


async def risk_carried_from_versions(uow: UnitOfWork, source_ids: list[UUID]) -> dict[UUID, int]:
    """`{source Risk id: its version number}`."""
    if not source_ids:
        return {}
    rows = await uow.session.execute(
        select(RiskRow.id, EstimateVersionRow.version)
        .join(EstimateVersionRow, EstimateVersionRow.id == RiskRow.version_id)
        .where(RiskRow.id.in_(source_ids))
    )
    return {row.id: row.version for row in rows}


# --- the Baseline (Story 9.7) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    id: UUID
    opportunity_id: UUID
    estimate_version_id: UUID
    previous_version_id: UUID | None
    set_at: datetime
    set_by: UUID


def _baseline(row: BaselineRow) -> BaselineRecord:
    return BaselineRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        estimate_version_id=row.estimate_version_id,
        previous_version_id=row.previous_version_id,
        set_at=row.set_at,
        set_by=row.set_by,
    )


_LATEST_BASELINE = (BaselineRow.set_at.desc(), BaselineRow.id.desc())


async def current_baseline(uow: UnitOfWork, opportunity_id: UUID) -> BaselineRecord | None:
    """The Opportunity's current Baseline (its latest row), or None before the first."""
    row = (
        await uow.session.execute(
            select(BaselineRow)
            .where(BaselineRow.opportunity_id == opportunity_id)
            .order_by(*_LATEST_BASELINE)
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _baseline(row)


async def current_baselines(
    uow: UnitOfWork, opportunity_ids: list[UUID]
) -> dict[UUID, BaselineRecord]:
    """Each of these Opportunities' current Baseline, in one query; ones with none are left
    out."""
    if not opportunity_ids:
        return {}
    rows = await uow.session.execute(
        select(BaselineRow)
        .where(BaselineRow.opportunity_id.in_(opportunity_ids))
        .order_by(*_LATEST_BASELINE)
    )
    found: dict[UUID, BaselineRecord] = {}
    for row in rows.scalars():
        found.setdefault(row.opportunity_id, _baseline(row))
    return found


async def insert_baseline(
    uow: UnitOfWork,
    *,
    baseline_id: UUID,
    opportunity_id: UUID,
    estimate_version_id: UUID,
    previous_version_id: UUID | None,
    set_by: UUID,
) -> BaselineRecord:
    """A new Baseline row. `set_at` is the clock time (after the caller took the
    Opportunity's lock), so the latest row is always the newest Baseline."""
    await uow.session.execute(
        insert(BaselineRow).values(
            id=baseline_id,
            opportunity_id=opportunity_id,
            estimate_version_id=estimate_version_id,
            previous_version_id=previous_version_id,
            set_at=func.clock_timestamp(),
            set_by=set_by,
        )
    )
    row = (
        await uow.session.execute(
            select(BaselineRow)
            .where(BaselineRow.id == baseline_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _baseline(row)


async def versions_of(uow: UnitOfWork, opportunity_id: UUID) -> list[VersionRecord]:
    """Every Estimate Version of the Opportunity, whatever its status, newest first."""
    rows = await uow.session.execute(
        select(EstimateVersionRow)
        .where(EstimateVersionRow.opportunity_id == opportunity_id)
        .order_by(EstimateVersionRow.version.desc())
        .execution_options(populate_existing=True)
    )
    return [_version(row) for row in rows.scalars()]


async def version_reasons(uow: UnitOfWork, version_ids: list[UUID]) -> dict[UUID, str]:
    """Story 9.7: the reason a person gave for each of these versions' **New version** (Story
    9.4, kept in its `estimates.estimate_version.created` trace event); versions with none are
    left out."""
    if not version_ids:
        return {}
    rows = await uow.session.execute(
        select(TraceEvent.subject_id, TraceEvent.payload).where(
            TraceEvent.subject_type == "estimates.estimate_version",
            TraceEvent.subject_id.in_(version_ids),
            TraceEvent.event_type == "estimates.estimate_version.created",
        )
    )
    found: dict[UUID, str] = {}
    for subject_id, payload in rows:
        reason = payload.get("reason") if isinstance(payload, dict) else None
        if isinstance(reason, str) and reason:
            found[subject_id] = reason
    return found


# --- trace reads for lineage and compare (Story 9.9) ----------------------------------------


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """A stored trace event, as lineage and compare read it (ids, kinds and the stored
    payload; never written here)."""

    id: UUID
    occurred_at: datetime
    event_type: str
    actor_type: str
    actor_id: str
    subject_type: str
    subject_id: UUID
    subject_version: int | None
    payload: dict[str, Any]


_TRACE_COLUMNS = (
    TraceEvent.id,
    TraceEvent.occurred_at,
    TraceEvent.event_type,
    TraceEvent.actor_type,
    TraceEvent.actor_id,
    TraceEvent.subject_type,
    TraceEvent.subject_id,
    TraceEvent.subject_version,
    TraceEvent.payload,
)


def _trace(row: Any) -> TraceRecord:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return TraceRecord(
        id=row.id,
        occurred_at=row.occurred_at,
        event_type=row.event_type,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_version=row.subject_version,
        payload=dict(payload),
    )


_OLDEST_FIRST = (TraceEvent.occurred_at, TraceEvent.id)


async def subject_events(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    subject_type: str,
    subject_ids: list[UUID],
    event_types: tuple[str, ...],
) -> list[TraceRecord]:
    """The Opportunity's events of these types about these subjects, oldest first (served by
    the `(subject_type, subject_id)` index)."""
    if not subject_ids:
        return []
    rows = await uow.session.execute(
        select(*_TRACE_COLUMNS)
        .where(
            TraceEvent.opportunity_id == opportunity_id,
            TraceEvent.subject_type == subject_type,
            TraceEvent.subject_id.in_(subject_ids),
            TraceEvent.event_type.in_(event_types),
        )
        .order_by(*_OLDEST_FIRST)
    )
    return [_trace(row) for row in rows]


async def line_edit_events(
    uow: UnitOfWork, opportunity_id: UUID, line_ids: list[UUID]
) -> list[TraceRecord]:
    """Every `estimates.estimate_line.edited` event of these lines, oldest first."""
    return await subject_events(
        uow,
        opportunity_id,
        subject_type="estimates.estimate_line",
        subject_ids=line_ids,
        event_types=("estimates.estimate_line.edited",),
    )


async def payload_events(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    event_type: str,
    key: str,
    values: list[str],
) -> list[TraceRecord]:
    """The Opportunity's events of `event_type` whose payload `key` is one of `values`
    (e.g. a Conflict decision's `line_id`), oldest first (the `(opportunity_id,
    occurred_at)` index narrows to the Opportunity)."""
    if not values:
        return []
    rows = await uow.session.execute(
        select(*_TRACE_COLUMNS)
        .where(
            TraceEvent.opportunity_id == opportunity_id,
            TraceEvent.event_type == event_type,
            TraceEvent.payload[key].astext.in_(values),
        )
        .order_by(*_OLDEST_FIRST)
    )
    return [_trace(row) for row in rows]


async def events_between(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    start: datetime,
    end: datetime,
    event_types: tuple[str, ...],
) -> list[TraceRecord]:
    """The Opportunity's events of these types with `start <= occurred_at <= end`, oldest
    first (served by the `(opportunity_id, occurred_at)` index)."""
    rows = await uow.session.execute(
        select(*_TRACE_COLUMNS)
        .where(
            TraceEvent.opportunity_id == opportunity_id,
            TraceEvent.occurred_at >= start,
            TraceEvent.occurred_at <= end,
            TraceEvent.event_type.in_(event_types),
        )
        .order_by(*_OLDEST_FIRST)
    )
    return [_trace(row) for row in rows]
