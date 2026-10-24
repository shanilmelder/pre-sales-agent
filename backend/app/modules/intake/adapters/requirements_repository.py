"""Persistence for extractions, Source passages and Requirements (Story 2.5 Part A),
Requirement versions and confirmation (Story 2.6), pending Requirement changes (Story
2.7), and creating, deleting, splitting and merging Requirements with their stable numbers
(Story 2.6 remainder). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    Uuid,
    any_,
    delete,
    exists,
    func,
    insert,
    literal,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.intake.adapters.models import (
    ExtractionRow,
    RequirementChangeRow,
    RequirementEvidenceRow,
    RequirementIntegrationTypeRow,
    RequirementRow,
    RequirementVersionRow,
    SourceParseRow,
    SourcePassageRow,
    SourceRow,
    SourceVersionRow,
)
from app.platform.ids import new_id
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ExtractionRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    error_code: str | None
    requirement_count: int | None
    dropped_count: int | None
    source_count: int | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParsedVersion:
    """The latest version of a Source, when that version is `parsed`."""

    source_id: UUID
    version: int
    kind: str
    number: int
    """The Source's position among the Opportunity's Sources, oldest first (1-based): `S<n>`."""


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    requirement_id: UUID
    passage_id: UUID
    source_id: UUID
    source_version: int
    filename: str


@dataclass(frozen=True, slots=True)
class RequirementRecord:
    id: UUID
    text: str
    classification: str
    origin: str
    locked_by_human: bool
    version: int
    row_version: int
    created_at: datetime
    confirmed_at: datetime | None = None
    confirmed_by: UUID | None = None
    number: int = 0
    """Its stable `R<n>` within the Opportunity (Story 2.6)."""
    status: str = "active"


@dataclass(frozen=True, slots=True)
class VersionAuthor:
    """Who wrote a Requirement's current version (an actor id), and when."""

    created_by: str
    created_at: datetime


# --- extractions ----------------------------------------------------------------------------


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise extraction bookkeeping for one Opportunity until commit: queueing, a job
    starting, and accepting a result."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"intake.extraction:{opportunity_id}"},
    )


def _extraction(row: ExtractionRow) -> ExtractionRecord:
    return ExtractionRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        error_code=row.error_code,
        requirement_count=row.requirement_count,
        dropped_count=row.dropped_count,
        source_count=row.source_count,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def insert_extraction(uow: UnitOfWork, *, extraction_id: UUID, opportunity_id: UUID) -> None:
    await uow.session.execute(
        insert(ExtractionRow).values(
            id=extraction_id, opportunity_id=opportunity_id, status="queued"
        )
    )


async def get_extraction(
    uow: UnitOfWork, extraction_id: UUID, *, for_update: bool = False
) -> ExtractionRecord | None:
    statement = select(ExtractionRow).where(ExtractionRow.id == extraction_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _extraction(row)


async def latest_extraction(uow: UnitOfWork, opportunity_id: UUID) -> ExtractionRecord | None:
    row = (
        await uow.session.execute(
            select(ExtractionRow)
            .where(ExtractionRow.opportunity_id == opportunity_id)
            .order_by(ExtractionRow.created_at.desc(), ExtractionRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _extraction(row)


async def extraction_in(
    uow: UnitOfWork, opportunity_id: UUID, statuses: tuple[str, ...]
) -> UUID | None:
    """An extraction of the Opportunity in one of `statuses` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(ExtractionRow.id)
            .where(
                ExtractionRow.opportunity_id == opportunity_id,
                ExtractionRow.status.in_(statuses),
            )
            .order_by(ExtractionRow.created_at, ExtractionRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def newer_succeeded(uow: UnitOfWork, record: ExtractionRecord) -> bool:
    """Whether an extraction of the same Opportunity queued after this one has succeeded."""
    newer = await uow.session.execute(
        select(ExtractionRow.id)
        .where(
            ExtractionRow.opportunity_id == record.opportunity_id,
            ExtractionRow.status == "succeeded",
            tuple_(ExtractionRow.created_at, ExtractionRow.id) > (record.created_at, record.id),
        )
        .limit(1)
    )
    return newer.first() is not None


async def fail_stale_extractions(
    uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta, error_code: str
) -> int:
    """Mark the Opportunity's extractions still `queued` or `running` after `older_than`
    `failed` with `error_code`. Returns how many changed."""
    result = await uow.session.execute(
        update(ExtractionRow)
        .where(
            ExtractionRow.opportunity_id == opportunity_id,
            ExtractionRow.status.in_(("queued", "running")),
            ExtractionRow.created_at < func.now() - older_than,
        )
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(ExtractionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def update_extraction(
    uow: UnitOfWork,
    extraction_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    requirement_count: int | None = None,
    dropped_count: int | None = None,
    source_count: int | None = None,
    finished: bool = False,
) -> bool:
    """Move the extraction to `status` if it is in one of `from_statuses`. Counts left None
    keep their value. False (and no change) otherwise."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    for name, value in (
        ("requirement_count", requirement_count),
        ("dropped_count", dropped_count),
        ("source_count", source_count),
    ):
        if value is not None:
            values[name] = value
    if finished:
        values["finished_at"] = func.now()
    result = await uow.session.execute(
        update(ExtractionRow)
        .where(ExtractionRow.id == extraction_id, ExtractionRow.status.in_(from_statuses))
        .values(**values)
        .returning(ExtractionRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Sources --------------------------------------------------------------------------------


async def source_numbers(uow: UnitOfWork, opportunity_id: UUID) -> dict[UUID, int]:
    """Each Source's `S<n>` number: its position among the Opportunity's Sources, oldest
    first (1-based). Stable: Sources are never removed."""
    rows = await uow.session.execute(
        select(SourceRow.id)
        .where(SourceRow.opportunity_id == opportunity_id)
        .order_by(SourceRow.created_at, SourceRow.id)
    )
    return {source_id: number for number, source_id in enumerate(rows.scalars(), start=1)}


async def newest_parsed_versions(uow: UnitOfWork, opportunity_id: UUID) -> list[ParsedVersion]:
    """The newest `parsed` version of every Source of the Opportunity that has one, in
    `S<n>` order. A newer version that failed or isn't parsed yet doesn't hide it."""
    numbers = await source_numbers(uow, opportunity_id)
    newest = (
        select(
            SourceParseRow.source_id.label("source_id"),
            func.max(SourceParseRow.version).label("version"),
        )
        .join(SourceRow, SourceRow.id == SourceParseRow.source_id)
        .where(SourceRow.opportunity_id == opportunity_id, SourceParseRow.status == "parsed")
        .group_by(SourceParseRow.source_id)
        .subquery("newest")
    )
    rows = await uow.session.execute(
        select(newest.c.source_id, newest.c.version, SourceRow.kind).join(
            SourceRow, SourceRow.id == newest.c.source_id
        )
    )
    found = [
        ParsedVersion(
            source_id=row.source_id,
            version=row.version,
            kind=row.kind,
            number=numbers[row.source_id],
        )
        for row in rows
    ]
    return sorted(found, key=lambda v: v.number)


# --- passages and Requirements ----------------------------------------------------------------


async def passage(uow: UnitOfWork, *, source_id: UUID, version: int, start: int, end: int) -> UUID:
    """The id of the passage for this span, inserted if new (passages are immutable and one
    row per span, so an existing one is reused)."""
    inserted = (
        await uow.session.execute(
            pg_insert(SourcePassageRow)
            .values(id=new_id(), source_id=source_id, source_version=version, start=start, end=end)
            .on_conflict_do_nothing(index_elements=["source_id", "source_version", "start", "end"])
            .returning(SourcePassageRow.id)
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted
    return (
        await uow.session.execute(
            select(SourcePassageRow.id).where(
                SourcePassageRow.source_id == source_id,
                SourcePassageRow.source_version == version,
                SourcePassageRow.start == start,
                SourcePassageRow.end == end,
            )
        )
    ).scalar_one()


async def lock_numbers(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise allocating Requirement numbers for one Opportunity until commit, so two
    concurrent inserts never take the same `R<n>`."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"intake.requirement_number:{opportunity_id}"},
    )


async def next_number(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """The Opportunity's next Requirement number: one past the highest ever given (removed
    Requirements keep theirs, so a number is never reused). Takes `lock_numbers` first."""
    await lock_numbers(uow, opportunity_id)
    highest = (
        await uow.session.execute(
            select(func.max(RequirementRow.number)).where(
                RequirementRow.opportunity_id == opportunity_id
            )
        )
    ).scalar_one_or_none()
    return (highest or 0) + 1


async def insert_requirement(
    uow: UnitOfWork,
    *,
    requirement_id: UUID,
    opportunity_id: UUID,
    text_: str,
    classification: str,
    extraction_id: UUID | None,
    passage_ids: list[UUID],
    created_by: str,
    origin: str = "extracted",
    locked_by_human: bool = False,
) -> RequirementRecord:
    """An `active` Requirement at version 1 with the Opportunity's next number, citing the
    passages, and its version-1 history row (`created_by`: the actor id). Extraction inserts
    `extracted`, unlocked ones; a person's create, split and merge `human`, locked ones."""
    number = await next_number(uow, opportunity_id)
    row = (
        await uow.session.execute(
            insert(RequirementRow)
            .values(
                id=requirement_id,
                opportunity_id=opportunity_id,
                text=text_,
                classification=classification,
                origin=origin,
                locked_by_human=locked_by_human,
                status="active",
                version=1,
                extraction_id=extraction_id,
                row_version=1,
                number=number,
            )
            .returning(RequirementRow)
        )
    ).scalar_one()
    record = _requirement(row)
    if passage_ids:
        await uow.session.execute(
            insert(RequirementEvidenceRow),
            [{"requirement_id": requirement_id, "passage_id": pid} for pid in passage_ids],
        )
    await insert_version(
        uow,
        requirement_id=requirement_id,
        version=1,
        text_=text_,
        classification=classification,
        created_by=created_by,
    )
    return record


async def insert_version(
    uow: UnitOfWork,
    *,
    requirement_id: UUID,
    version: int,
    text_: str,
    classification: str,
    created_by: str,
) -> None:
    """One immutable history row of a Requirement (Story 2.6)."""
    await uow.session.execute(
        insert(RequirementVersionRow).values(
            requirement_id=requirement_id,
            version=version,
            text=text_,
            classification=classification,
            created_by=created_by,
        )
    )


def _requirement(row: RequirementRow) -> RequirementRecord:
    return RequirementRecord(
        id=row.id,
        text=row.text,
        classification=row.classification,
        origin=row.origin,
        locked_by_human=row.locked_by_human,
        version=row.version,
        row_version=row.row_version,
        created_at=row.created_at,
        confirmed_at=row.confirmed_at,
        confirmed_by=row.confirmed_by,
        number=row.number,
        status=row.status,
    )


async def requirements_in(
    uow: UnitOfWork, opportunity_id: UUID, status: str = "active"
) -> list[RequirementRecord]:
    """The Opportunity's Requirements in `status`, by number (oldest first)."""
    rows = await uow.session.execute(
        select(RequirementRow)
        .where(RequirementRow.opportunity_id == opportunity_id, RequirementRow.status == status)
        .order_by(RequirementRow.number)
    )
    return [_requirement(row) for row in rows.scalars()]


async def removed_requirements(uow: UnitOfWork, opportunity_id: UUID) -> list[RequirementRecord]:
    """The Requirements a person removed (Story 2.6): `deleted` ones, and `superseded` ones
    that are locked (split or merged away; extraction before Story 2.7 only superseded
    unlocked rows), by number."""
    rows = await uow.session.execute(
        select(RequirementRow)
        .where(
            RequirementRow.opportunity_id == opportunity_id,
            (RequirementRow.status == "deleted")
            | ((RequirementRow.status == "superseded") & RequirementRow.locked_by_human.is_(True)),
        )
        .order_by(RequirementRow.number)
    )
    return [_requirement(row) for row in rows.scalars()]


async def active_requirements(uow: UnitOfWork, opportunity_id: UUID) -> list[RequirementRecord]:
    """The Opportunity's `active` Requirements, by number (oldest first)."""
    return await requirements_in(uow, opportunity_id)


# --- human edits (Story 2.6) ----------------------------------------------------------------


async def active_requirement(
    uow: UnitOfWork, opportunity_id: UUID, requirement_id: UUID
) -> RequirementRecord | None:
    """The Requirement with this id, if it is `active` and belongs to the Opportunity."""
    row = (
        await uow.session.execute(
            select(RequirementRow).where(
                RequirementRow.id == requirement_id,
                RequirementRow.opportunity_id == opportunity_id,
                RequirementRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    return None if row is None else _requirement(row)


async def edit_requirement(
    uow: UnitOfWork,
    requirement_id: UUID,
    *,
    expected_row_version: int,
    text_: str,
    classification: str,
    clear_confirmation: bool = False,
) -> RequirementRecord | None:
    """Store a human edit: the next version, `origin` `human`, locked; unconfirmed when
    `clear_confirmation`. Only while the Requirement is `active` at `expected_row_version`;
    None (and no change) otherwise."""
    values: dict[str, object] = {
        "text": text_,
        "classification": classification,
        "origin": "human",
        "locked_by_human": True,
        "version": RequirementRow.version + 1,
        "row_version": RequirementRow.row_version + 1,
        "updated_at": func.now(),
    }
    if clear_confirmation:
        values["confirmed_at"] = None
        values["confirmed_by"] = None
    row = (
        await uow.session.execute(
            update(RequirementRow)
            .where(
                RequirementRow.id == requirement_id,
                RequirementRow.status == "active",
                RequirementRow.row_version == expected_row_version,
            )
            .values(**values)
            .returning(RequirementRow)
            # Rows read earlier in the session are refreshed, not served stale.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _requirement(row)


_CONFIRMED = {
    "locked_by_human": True,
    "row_version": RequirementRow.row_version + 1,
    "updated_at": func.now(),
    "confirmed_at": func.now(),
}


async def confirm_requirement(
    uow: UnitOfWork, requirement_id: UUID, *, expected_row_version: int, user_id: UUID
) -> RequirementRecord | None:
    """Confirm the Requirement and lock it. Only while it is `active`, unconfirmed and at
    `expected_row_version`; None (and no change) otherwise."""
    row = (
        await uow.session.execute(
            update(RequirementRow)
            .where(
                RequirementRow.id == requirement_id,
                RequirementRow.status == "active",
                RequirementRow.confirmed_at.is_(None),
                RequirementRow.row_version == expected_row_version,
            )
            .values(**_CONFIRMED, confirmed_by=user_id)
            .returning(RequirementRow)
            # Rows read earlier in the session are refreshed, not served stale.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _requirement(row)


async def confirm_all(
    uow: UnitOfWork, opportunity_id: UUID, *, user_id: UUID
) -> list[RequirementRecord]:
    """Confirm and lock every `active`, unconfirmed Requirement of the Opportunity. Returns
    the ones confirmed, oldest first."""
    rows = await uow.session.execute(
        update(RequirementRow)
        .where(
            RequirementRow.opportunity_id == opportunity_id,
            RequirementRow.status == "active",
            RequirementRow.confirmed_at.is_(None),
        )
        .values(**_CONFIRMED, confirmed_by=user_id)
        .returning(RequirementRow)
        .execution_options(synchronize_session=False)
    )
    return sorted((_requirement(row) for row in rows.scalars()), key=lambda r: r.number)


async def current_version_authors(
    uow: UnitOfWork, requirements: list[RequirementRecord]
) -> dict[UUID, VersionAuthor]:
    """Who wrote each Requirement's current version, from its history."""
    if not requirements:
        return {}
    rows = await uow.session.execute(
        select(
            RequirementVersionRow.requirement_id,
            RequirementVersionRow.created_by,
            RequirementVersionRow.created_at,
        ).where(
            tuple_(RequirementVersionRow.requirement_id, RequirementVersionRow.version).in_(
                [(r.id, r.version) for r in requirements]
            )
        )
    )
    return {
        row.requirement_id: VersionAuthor(created_by=row.created_by, created_at=row.created_at)
        for row in rows
    }


async def evidence_for(uow: UnitOfWork, requirement_ids: list[UUID]) -> list[EvidenceRecord]:
    """The cited passages of these Requirements, each with its Source version's file name,
    in Source and span order."""
    if not requirement_ids:
        return []
    rows = await uow.session.execute(
        select(
            RequirementEvidenceRow.requirement_id,
            SourcePassageRow.id.label("passage_id"),
            SourcePassageRow.source_id,
            SourcePassageRow.source_version,
            SourceVersionRow.filename,
        )
        .join(SourcePassageRow, SourcePassageRow.id == RequirementEvidenceRow.passage_id)
        .join(
            SourceVersionRow,
            (SourceVersionRow.source_id == SourcePassageRow.source_id)
            & (SourceVersionRow.version == SourcePassageRow.source_version),
        )
        .where(RequirementEvidenceRow.requirement_id.in_(requirement_ids))
        .order_by(
            RequirementEvidenceRow.requirement_id,
            SourcePassageRow.source_id,
            SourcePassageRow.start,
            SourcePassageRow.end,
        )
    )
    return [
        EvidenceRecord(
            requirement_id=row.requirement_id,
            passage_id=row.passage_id,
            source_id=row.source_id,
            source_version=row.source_version,
            filename=row.filename,
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class PassageRecord:
    id: UUID
    source_id: UUID
    source_version: int
    start: int
    end: int
    filename: str


async def passage_in(
    uow: UnitOfWork, opportunity_id: UUID, passage_id: UUID
) -> PassageRecord | None:
    """The passage with this id, with its Source version's file name, if its Source belongs
    to the Opportunity (Story 2.5 Part B)."""
    row = (
        await uow.session.execute(
            select(
                SourcePassageRow.id,
                SourcePassageRow.source_id,
                SourcePassageRow.source_version,
                SourcePassageRow.start,
                SourcePassageRow.end,
                SourceVersionRow.filename,
            )
            .join(SourceRow, SourceRow.id == SourcePassageRow.source_id)
            .join(
                SourceVersionRow,
                (SourceVersionRow.source_id == SourcePassageRow.source_id)
                & (SourceVersionRow.version == SourcePassageRow.source_version),
            )
            .where(SourcePassageRow.id == passage_id, SourceRow.opportunity_id == opportunity_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return PassageRecord(
        id=row.id,
        source_id=row.source_id,
        source_version=row.source_version,
        start=row.start,
        end=row.end,
        filename=row.filename,
    )


async def version_texts(
    uow: UnitOfWork, opportunity_id: UUID, refs: list[tuple[UUID, int]]
) -> dict[tuple[UUID, int], tuple[str, str]]:
    """The text and classification of these Requirement versions `(id, version)` of the
    Opportunity, from their immutable history (Story 4.3: a Gap cites a version)."""
    if not refs:
        return {}
    rows = await uow.session.execute(
        select(
            RequirementVersionRow.requirement_id,
            RequirementVersionRow.version,
            RequirementVersionRow.text,
            RequirementVersionRow.classification,
        )
        .join(RequirementRow, RequirementRow.id == RequirementVersionRow.requirement_id)
        .where(
            RequirementRow.opportunity_id == opportunity_id,
            tuple_(RequirementVersionRow.requirement_id, RequirementVersionRow.version).in_(refs),
        )
    )
    return {(row.requirement_id, row.version): (row.text, row.classification) for row in rows}


async def requirement_version_owners(
    uow: UnitOfWork, refs: list[tuple[UUID, int]]
) -> dict[tuple[UUID, int], UUID]:
    """`{(id, version): opportunity_id}` for the Requirement versions that exist (Story 6.6:
    the `requirement` Evidence resolver)."""
    if not refs:
        return {}
    rows = await uow.session.execute(
        select(
            RequirementVersionRow.requirement_id,
            RequirementVersionRow.version,
            RequirementRow.opportunity_id,
        )
        .join(RequirementRow, RequirementRow.id == RequirementVersionRow.requirement_id)
        .where(
            tuple_(RequirementVersionRow.requirement_id, RequirementVersionRow.version).in_(refs)
        )
    )
    return {(row.requirement_id, row.version): row.opportunity_id for row in rows}


async def source_version_owners(
    uow: UnitOfWork, refs: list[tuple[UUID, int]]
) -> dict[tuple[UUID, int], tuple[UUID, str]]:
    """`{(id, version): (opportunity_id, filename)}` for the Source versions that exist
    (Story 6.6: the `source_document` Evidence resolver)."""
    if not refs:
        return {}
    rows = await uow.session.execute(
        select(
            SourceVersionRow.source_id,
            SourceVersionRow.version,
            SourceVersionRow.filename,
            SourceRow.opportunity_id,
        )
        .join(SourceRow, SourceRow.id == SourceVersionRow.source_id)
        .where(tuple_(SourceVersionRow.source_id, SourceVersionRow.version).in_(refs))
    )
    return {(row.source_id, row.version): (row.opportunity_id, row.filename) for row in rows}


# --- incremental intake (Story 2.7) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitedPassage:
    requirement_id: UUID
    passage_id: UUID
    source_id: UUID
    source_version: int
    start: int
    end: int


async def active_cited_passages(
    uow: UnitOfWork, opportunity_id: UUID, status: str = "active"
) -> list[CitedPassage]:
    """The passages every Requirement of the Opportunity in `status` (by default the active
    ones) cites, with their spans."""
    rows = await uow.session.execute(
        select(
            RequirementEvidenceRow.requirement_id,
            SourcePassageRow.id.label("passage_id"),
            SourcePassageRow.source_id,
            SourcePassageRow.source_version,
            SourcePassageRow.start,
            SourcePassageRow.end,
        )
        .join(SourcePassageRow, SourcePassageRow.id == RequirementEvidenceRow.passage_id)
        .join(RequirementRow, RequirementRow.id == RequirementEvidenceRow.requirement_id)
        .where(RequirementRow.opportunity_id == opportunity_id, RequirementRow.status == status)
        .order_by(SourcePassageRow.source_id, SourcePassageRow.start, SourcePassageRow.end)
    )
    return [
        CitedPassage(
            requirement_id=row.requirement_id,
            passage_id=row.passage_id,
            source_id=row.source_id,
            source_version=row.source_version,
            start=row.start,
            end=row.end,
        )
        for row in rows
    ]


async def version_extracted(
    uow: UnitOfWork,
    requirement_id: UUID,
    *,
    expected_row_version: int,
    text_: str,
    classification: str,
) -> RequirementRecord | None:
    """Store extraction's refinement of an unlocked Requirement: the next version, still
    `extracted` and unlocked. Only while it is `active`, unlocked and at
    `expected_row_version`; None (and no change) otherwise."""
    row = (
        await uow.session.execute(
            update(RequirementRow)
            .where(
                RequirementRow.id == requirement_id,
                RequirementRow.status == "active",
                RequirementRow.locked_by_human.is_(False),
                RequirementRow.row_version == expected_row_version,
            )
            .values(
                text=text_,
                classification=classification,
                version=RequirementRow.version + 1,
                row_version=RequirementRow.row_version + 1,
                updated_at=func.now(),
            )
            .returning(RequirementRow)
            # Rows read earlier in the session are refreshed, not served stale.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _requirement(row)


async def link_evidence(uow: UnitOfWork, requirement_id: UUID, passage_ids: list[UUID]) -> None:
    """Make the Requirement cite these passages too (ones it cites already are skipped)."""
    if not passage_ids:
        return
    await uow.session.execute(
        pg_insert(RequirementEvidenceRow)
        .values([{"requirement_id": requirement_id, "passage_id": pid} for pid in passage_ids])
        .on_conflict_do_nothing(index_elements=["requirement_id", "passage_id"])
    )


async def bump_row_version(
    uow: UnitOfWork, requirement_id: UUID, *, expected_row_version: int | None = None
) -> RequirementRecord | None:
    """Bump the active Requirement's `row_version` (its read model changed), only at
    `expected_row_version` when given; None (and no change) otherwise."""
    statement = update(RequirementRow).where(
        RequirementRow.id == requirement_id, RequirementRow.status == "active"
    )
    if expected_row_version is not None:
        statement = statement.where(RequirementRow.row_version == expected_row_version)
    row = (
        await uow.session.execute(
            statement.values(row_version=RequirementRow.row_version + 1, updated_at=func.now())
            .returning(RequirementRow)
            # Rows read earlier in the session are refreshed, not served stale.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _requirement(row)


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    id: UUID
    requirement_id: UUID
    base_version: int
    text: str = field(repr=False)
    classification: str
    passage_ids: tuple[UUID, ...]
    status: str
    row_version: int
    created_at: datetime


def _change(row: RequirementChangeRow) -> ChangeRecord:
    return ChangeRecord(
        id=row.id,
        requirement_id=row.requirement_id,
        base_version=row.base_version,
        text=row.text,
        classification=row.classification,
        passage_ids=tuple(row.passage_ids),
        status=row.status,
        row_version=row.row_version,
        created_at=row.created_at,
    )


async def open_changes(
    uow: UnitOfWork, requirement_ids: list[UUID], *, for_update: bool = False
) -> dict[UUID, ChangeRecord]:
    """The `open` change of each of these Requirements that has one."""
    if not requirement_ids:
        return {}
    statement = select(RequirementChangeRow).where(
        RequirementChangeRow.requirement_id.in_(requirement_ids),
        RequirementChangeRow.status == "open",
    )
    if for_update:
        statement = statement.with_for_update()
    rows = await uow.session.execute(statement)
    return {row.requirement_id: _change(row) for row in rows.scalars()}


async def rejected_passage_sets(uow: UnitOfWork, requirement_id: UUID) -> set[tuple[UUID, ...]]:
    """The (sorted) passage sets of the Requirement's rejected changes."""
    rows = await uow.session.execute(
        select(RequirementChangeRow.passage_ids).where(
            RequirementChangeRow.requirement_id == requirement_id,
            RequirementChangeRow.status == "rejected",
        )
    )
    return {tuple(sorted(ids)) for ids in rows.scalars()}


async def insert_change(
    uow: UnitOfWork,
    *,
    change_id: UUID,
    requirement_id: UUID,
    base_version: int,
    text_: str,
    classification: str,
    passage_ids: list[UUID],
    extraction_id: UUID | None,
) -> None:
    """An `open` change."""
    await uow.session.execute(
        insert(RequirementChangeRow).values(
            id=change_id,
            requirement_id=requirement_id,
            base_version=base_version,
            text=text_,
            classification=classification,
            passage_ids=passage_ids,
            status="open",
            extraction_id=extraction_id,
            row_version=1,
        )
    )


async def close_change(
    uow: UnitOfWork,
    change_id: UUID,
    *,
    status: str,
    decided_by: UUID | None = None,
    reason: str | None = None,
) -> bool:
    """Move an `open` change to `status` (`accepted` and `rejected` with who decided, and
    now). False (and no change) when it is no longer open."""
    values: dict[str, object] = {
        "status": status,
        "reason": reason,
        "row_version": RequirementChangeRow.row_version + 1,
    }
    if decided_by is not None:
        values["decided_by"] = decided_by
        values["decided_at"] = func.now()
    result = await uow.session.execute(
        update(RequirementChangeRow)
        .where(RequirementChangeRow.id == change_id, RequirementChangeRow.status == "open")
        .values(**values)
        .returning(RequirementChangeRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


async def passages_by_id(uow: UnitOfWork, passage_ids: list[UUID]) -> dict[UUID, PassageRecord]:
    """These passages with their Source version's file name, keyed by id."""
    if not passage_ids:
        return {}
    rows = await uow.session.execute(
        select(
            SourcePassageRow.id,
            SourcePassageRow.source_id,
            SourcePassageRow.source_version,
            SourcePassageRow.start,
            SourcePassageRow.end,
            SourceVersionRow.filename,
        )
        .join(
            SourceVersionRow,
            (SourceVersionRow.source_id == SourcePassageRow.source_id)
            & (SourceVersionRow.version == SourcePassageRow.source_version),
        )
        .where(SourcePassageRow.id.in_(passage_ids))
    )
    return {
        row.id: PassageRecord(
            id=row.id,
            source_id=row.source_id,
            source_version=row.source_version,
            start=row.start,
            end=row.end,
            filename=row.filename,
        )
        for row in rows
    }


# --- shaping the list (Story 2.6 remainder) -------------------------------------------------


async def remove_requirement(
    uow: UnitOfWork,
    requirement_id: UUID,
    *,
    expected_row_version: int,
    status: str,
    removal_reason: str | None = None,
) -> RequirementRecord | None:
    """Take the Requirement out of the active list: `deleted` (with its reason) or
    `superseded` (split or merged away), locked either way, so reconciliation knows a person
    removed it (Story 2.6 review decision). Only while it is `active` at
    `expected_row_version`; None (and no change) otherwise."""
    row = (
        await uow.session.execute(
            update(RequirementRow)
            .where(
                RequirementRow.id == requirement_id,
                RequirementRow.status == "active",
                RequirementRow.row_version == expected_row_version,
            )
            .values(
                status=status,
                removal_reason=removal_reason,
                locked_by_human=True,
                row_version=RequirementRow.row_version + 1,
                updated_at=func.now(),
            )
            .returning(RequirementRow)
            # Rows read earlier in the session are refreshed, not served stale.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _requirement(row)


async def evidence_passage_ids(uow: UnitOfWork, requirement_ids: list[UUID]) -> list[UUID]:
    """The passages these Requirements cite, without duplicates, in Source and span order."""
    if not requirement_ids:
        return []
    rows = await uow.session.execute(
        select(SourcePassageRow.id)
        .where(
            SourcePassageRow.id.in_(
                select(RequirementEvidenceRow.passage_id).where(
                    RequirementEvidenceRow.requirement_id.in_(requirement_ids)
                )
            )
        )
        .order_by(SourcePassageRow.source_id, SourcePassageRow.start, SourcePassageRow.end)
    )
    return list(rows.scalars())


# --- answers (Story 4.7) --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceCitation:
    """A Requirement whose Evidence cites a passage of a Source, and whether the
    Requirement was created after that passage's Source version was added."""

    requirement_id: UUID
    created_after_source: bool


async def requirements_citing_source(uow: UnitOfWork, source_id: UUID) -> list[SourceCitation]:
    """The Requirements whose Evidence cites a passage of any version of the Source."""
    rows = await uow.session.execute(
        select(
            RequirementEvidenceRow.requirement_id,
            func.bool_or(RequirementRow.created_at >= SourceVersionRow.uploaded_at).label(
                "created_after"
            ),
        )
        .join(SourcePassageRow, SourcePassageRow.id == RequirementEvidenceRow.passage_id)
        .join(RequirementRow, RequirementRow.id == RequirementEvidenceRow.requirement_id)
        .join(
            SourceVersionRow,
            (SourceVersionRow.source_id == SourcePassageRow.source_id)
            & (SourceVersionRow.version == SourcePassageRow.source_version),
        )
        .where(SourcePassageRow.source_id == source_id)
        .group_by(RequirementEvidenceRow.requirement_id)
    )
    return [
        SourceCitation(
            requirement_id=row.requirement_id, created_after_source=bool(row.created_after)
        )
        for row in rows
    ]


async def changes_citing_source(uow: UnitOfWork, source_id: UUID) -> list[tuple[UUID, str]]:
    """`(requirement_id, status)` of every change whose proposed passages include a passage
    of any version of the Source, newest first."""
    cites = (
        select(SourcePassageRow.id)
        .where(
            SourcePassageRow.source_id == source_id,
            SourcePassageRow.id == any_(RequirementChangeRow.passage_ids),
        )
        .exists()
    )
    rows = await uow.session.execute(
        select(RequirementChangeRow.requirement_id, RequirementChangeRow.status)
        .where(cites)
        .order_by(RequirementChangeRow.created_at.desc(), RequirementChangeRow.id)
    )
    return [(row.requirement_id, row.status) for row in rows]


async def source_opportunity(uow: UnitOfWork, source_id: UUID) -> UUID | None:
    return (
        await uow.session.execute(select(SourceRow.opportunity_id).where(SourceRow.id == source_id))
    ).scalar_one_or_none()


# --- Integration Type tags (Story 4.1) ------------------------------------------------------

T = RequirementIntegrationTypeRow


async def integration_type_ids(
    uow: UnitOfWork, requirement_ids: list[UUID]
) -> dict[UUID, list[UUID]]:
    """`{requirement_id: [Integration Type entry ids]}` for the Requirements that have tags,
    each list in the order they were tagged (then by id)."""
    if not requirement_ids:
        return {}
    rows = await uow.session.execute(
        select(T.requirement_id, T.entry_id)
        .where(T.requirement_id.in_(requirement_ids))
        .order_by(T.requirement_id, T.tagged_at, T.entry_id)
    )
    result: dict[UUID, list[UUID]] = {}
    for requirement_id, entry_id in rows:
        result.setdefault(requirement_id, []).append(entry_id)
    return result


async def change_integration_types(
    uow: UnitOfWork,
    requirement_id: UUID,
    *,
    add: list[UUID],
    remove: list[UUID],
    tagged_by: UUID,
) -> None:
    """Add and remove these tags of the Requirement."""
    if remove:
        await uow.session.execute(
            delete(T).where(T.requirement_id == requirement_id, T.entry_id.in_(remove))
        )
    if add:
        await uow.session.execute(
            insert(T),
            [
                {"requirement_id": requirement_id, "entry_id": e, "tagged_by": tagged_by}
                for e in add
            ],
        )


async def copy_integration_types(
    uow: UnitOfWork, from_ids: list[UUID], to_id: UUID, *, tagged_by: UUID
) -> None:
    """Tag the Requirement `to_id` with the union of the tags of `from_ids` (a split child
    inherits its parent's, a merge takes the union)."""
    if not from_ids:
        return
    entries = select(T.entry_id).where(T.requirement_id.in_(from_ids)).distinct().subquery()
    await uow.session.execute(
        pg_insert(T)
        .from_select(
            ["requirement_id", "entry_id", "tagged_by"],
            select(literal(to_id, Uuid), entries.c.entry_id, literal(tagged_by, Uuid)),
        )
        .on_conflict_do_nothing(index_elements=["requirement_id", "entry_id"])
    )


async def integration_scope(uow: UnitOfWork, opportunity_id: UUID) -> tuple[list[UUID], int]:
    """The union of the tags of the Opportunity's active Requirements (sorted), and how many
    of its active Requirements classified `integration` have no tag."""
    active = (RequirementRow.opportunity_id == opportunity_id) & (RequirementRow.status == "active")
    tags = await uow.session.execute(
        select(T.entry_id)
        .join(RequirementRow, RequirementRow.id == T.requirement_id)
        .where(active)
        .distinct()
        .order_by(T.entry_id)
    )
    untagged = await uow.session.execute(
        select(func.count())
        .select_from(RequirementRow)
        .where(
            active,
            RequirementRow.classification == "integration",
            ~exists().where(T.requirement_id == RequirementRow.id),
        )
    )
    return list(tags.scalars()), int(untagged.scalar_one())
