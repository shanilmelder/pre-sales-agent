"""Persistence for extractions, Source passages and Requirements (Story 2.5 Part A). Runs
inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.intake.adapters.models import (
    ExtractionRow,
    RequirementEvidenceRow,
    RequirementRow,
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


async def supersede_extracted(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """Mark every `active`, `extracted`, unlocked Requirement of the Opportunity `superseded`.
    Locked ones are never touched. Returns how many changed."""
    result = await uow.session.execute(
        update(RequirementRow)
        .where(
            RequirementRow.opportunity_id == opportunity_id,
            RequirementRow.status == "active",
            RequirementRow.origin == "extracted",
            RequirementRow.locked_by_human.is_(False),
        )
        .values(
            status="superseded",
            updated_at=func.now(),
            row_version=RequirementRow.row_version + 1,
        )
        .returning(RequirementRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def insert_requirement(
    uow: UnitOfWork,
    *,
    requirement_id: UUID,
    opportunity_id: UUID,
    text_: str,
    classification: str,
    extraction_id: UUID,
    passage_ids: list[UUID],
) -> None:
    """An `active`, `extracted`, unlocked Requirement at version 1, citing the passages."""
    await uow.session.execute(
        insert(RequirementRow).values(
            id=requirement_id,
            opportunity_id=opportunity_id,
            text=text_,
            classification=classification,
            origin="extracted",
            locked_by_human=False,
            status="active",
            version=1,
            extraction_id=extraction_id,
            row_version=1,
        )
    )
    await uow.session.execute(
        insert(RequirementEvidenceRow),
        [{"requirement_id": requirement_id, "passage_id": pid} for pid in passage_ids],
    )


async def active_requirements(uow: UnitOfWork, opportunity_id: UUID) -> list[RequirementRecord]:
    """The Opportunity's `active` Requirements, oldest first."""
    rows = await uow.session.execute(
        select(RequirementRow)
        .where(RequirementRow.opportunity_id == opportunity_id, RequirementRow.status == "active")
        .order_by(RequirementRow.created_at, RequirementRow.id)
    )
    return [
        RequirementRecord(
            id=row.id,
            text=row.text,
            classification=row.classification,
            origin=row.origin,
            locked_by_human=row.locked_by_human,
            version=row.version,
            row_version=row.row_version,
            created_at=row.created_at,
        )
        for row in rows.scalars()
    ]


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
