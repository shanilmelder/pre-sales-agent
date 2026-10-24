"""Persistence for detections, Gaps, their Requirement links and their Clarification
Questions (Story 4.3). Runs inside the caller's Unit of Work."""

import json
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, func, insert, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.gaps.adapters.models import (
    AnswerMatchRow,
    DetectionRow,
    GapHistoryRow,
    GapRequirementRow,
    GapRow,
    QuestionRow,
)
from app.platform.events import EVENTS_CHANNEL
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class DetectionRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    error_code: str | None
    gap_count: int | None
    dropped_count: int | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class GapRecord:
    id: UUID
    opportunity_id: UUID
    title: str
    category: str
    trigger: dict[str, Any]
    why_it_matters: str
    impact: str
    impact_basis: str
    origin: str
    status: str
    converted_to: str | None
    row_version: int
    created_at: datetime
    dismiss_reason_kind: str | None = None
    dismiss_note: str | None = None
    dismissed_by: UUID | None = None
    dismissed_at: datetime | None = None
    changed_by: UUID | None = None
    touched_by_human: bool = False
    answered_on: date | None = None
    answered_by: UUID | None = None
    answer_passage_id: UUID | None = None
    checklist_applies: bool = True
    why_entry_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GapHistoryRecord:
    id: UUID
    gap_id: UUID
    kind: str
    actor_id: UUID | None
    at: datetime
    old_impact: str | None
    new_impact: str | None
    reason_kind: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class GapLinkRecord:
    gap_id: UUID
    requirement_id: UUID
    requirement_version: int


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    id: UUID
    gap_id: UUID
    text: str
    topic: str
    status: str
    status_changed_at: datetime
    row_version: int
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    edited_by_human: bool = False
    changed_by: UUID | None = None
    sent_on: date | None = None
    sent_by: UUID | None = None
    answered_on: date | None = None
    answered_by: UUID | None = None
    answer_passage_id: UUID | None = None
    from_checklist: bool = False


@dataclass(frozen=True, slots=True)
class AnswerMatchRecord:
    id: UUID
    opportunity_id: UUID
    question_id: UUID
    passage_id: UUID
    injection_suspected: bool
    status: str
    row_version: int
    created_at: datetime
    decided_by: UUID | None = None
    decided_at: datetime | None = None


TOUCHED_QUESTION_STATUSES = ("approved", "sent", "unanswered", "answered")
"""A question in one of these statuses was touched by a person (Stories 4.5, 4.6, 4.7)."""
OPEN_TO_ANSWER_STATUSES = ("sent", "unanswered")
"""A question in one of these statuses can be answered (Story 4.7)."""
GAPS_SOURCE = "gaps"


async def notify_gaps_changed(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Tell the Opportunity's event stream that its Gaps, questions or answer suggestions
    changed (Story 4.7). Delivered when the Unit of Work commits, and only then; Postgres
    folds identical notifications of one transaction into one. Ids only."""
    payload = json.dumps({"opportunity_id": str(opportunity_id), "source": GAPS_SOURCE})
    await uow.session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENTS_CHANNEL, "payload": payload},
    )


# --- detections -----------------------------------------------------------------------------


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise detection bookkeeping for one Opportunity until commit: queueing, a job
    starting, and accepting a result."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"gaps.detection:{opportunity_id}"},
    )


def _detection(row: DetectionRow) -> DetectionRecord:
    return DetectionRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        error_code=row.error_code,
        gap_count=row.gap_count,
        dropped_count=row.dropped_count,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def insert_detection(uow: UnitOfWork, *, detection_id: UUID, opportunity_id: UUID) -> None:
    await uow.session.execute(
        insert(DetectionRow).values(id=detection_id, opportunity_id=opportunity_id, status="queued")
    )


async def get_detection(
    uow: UnitOfWork, detection_id: UUID, *, for_update: bool = False
) -> DetectionRecord | None:
    statement = select(DetectionRow).where(DetectionRow.id == detection_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _detection(row)


async def latest_detection(uow: UnitOfWork, opportunity_id: UUID) -> DetectionRecord | None:
    row = (
        await uow.session.execute(
            select(DetectionRow)
            .where(DetectionRow.opportunity_id == opportunity_id)
            .order_by(DetectionRow.created_at.desc(), DetectionRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _detection(row)


async def detection_in(
    uow: UnitOfWork, opportunity_id: UUID, statuses: tuple[str, ...]
) -> UUID | None:
    """A detection of the Opportunity in one of `statuses` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(DetectionRow.id)
            .where(
                DetectionRow.opportunity_id == opportunity_id,
                DetectionRow.status.in_(statuses),
            )
            .order_by(DetectionRow.created_at, DetectionRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def newer_succeeded(uow: UnitOfWork, record: DetectionRecord) -> bool:
    """Whether a detection of the same Opportunity queued after this one has succeeded."""
    newer = await uow.session.execute(
        select(DetectionRow.id)
        .where(
            DetectionRow.opportunity_id == record.opportunity_id,
            DetectionRow.status == "succeeded",
            tuple_(DetectionRow.created_at, DetectionRow.id) > (record.created_at, record.id),
        )
        .limit(1)
    )
    return newer.first() is not None


async def fail_stale_detections(
    uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta, error_code: str
) -> int:
    """Mark the Opportunity's detections still `queued` or `running` after `older_than`
    `failed` with `error_code`. Returns how many changed."""
    result = await uow.session.execute(
        update(DetectionRow)
        .where(
            DetectionRow.opportunity_id == opportunity_id,
            DetectionRow.status.in_(("queued", "running")),
            DetectionRow.created_at < func.now() - older_than,
        )
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(DetectionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def update_detection(
    uow: UnitOfWork,
    detection_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    gap_count: int | None = None,
    dropped_count: int | None = None,
    finished: bool = False,
) -> bool:
    """Move the detection to `status` if it is in one of `from_statuses`. Counts left None
    keep their value. False (and no change) otherwise."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    if gap_count is not None:
        values["gap_count"] = gap_count
    if dropped_count is not None:
        values["dropped_count"] = dropped_count
    if finished:
        values["finished_at"] = func.now()
    result = await uow.session.execute(
        update(DetectionRow)
        .where(DetectionRow.id == detection_id, DetectionRow.status.in_(from_statuses))
        .values(**values)
        .returning(DetectionRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Gaps -----------------------------------------------------------------------------------


def _untouched_question_or_none() -> ColumnElement[bool]:
    """True for a Gap whose question (if any) no person has edited, approved, sent or marked
    "No answer"."""
    touched = (
        select(QuestionRow.id)
        .where(
            QuestionRow.gap_id == GapRow.id,
            or_(
                QuestionRow.edited_by_human.is_(True),
                QuestionRow.status.in_(TOUCHED_QUESTION_STATUSES),
            ),
        )
        .exists()
    )
    return ~touched


async def supersede_detected(uow: UnitOfWork, opportunity_id: UUID) -> tuple[int, int]:
    """Mark every `open`, `detected` Gap of the Opportunity `superseded`, together with its
    Clarification Question, except those whose question a person has edited or approved
    (Story 4.5), sent or marked "No answer" (Story 4.6), or whose impact a person changed
    or that a person reopened (`touched_by_human`, Story 4.4): they stay as they are.
    Dismissed Gaps are never touched. Returns how many Gaps changed and how many were kept.
    The caller holds
    `lock_opportunity`, which question and Gap edits take too."""
    gap_ids = list(
        (
            await uow.session.execute(
                update(GapRow)
                .where(
                    GapRow.opportunity_id == opportunity_id,
                    GapRow.status == "open",
                    GapRow.origin == "detected",
                    GapRow.touched_by_human.is_(False),
                    _untouched_question_or_none(),
                )
                .values(status="superseded", row_version=GapRow.row_version + 1)
                .returning(GapRow.id)
                .execution_options(synchronize_session=False)
            )
        ).scalars()
    )
    if gap_ids:
        await uow.session.execute(
            update(QuestionRow)
            .where(QuestionRow.gap_id.in_(gap_ids), QuestionRow.status != "superseded")
            .values(
                status="superseded",
                status_changed_at=func.now(),
                row_version=QuestionRow.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
    kept = (
        await uow.session.execute(
            select(func.count())
            .select_from(GapRow)
            .where(
                GapRow.opportunity_id == opportunity_id,
                GapRow.status == "open",
                GapRow.origin == "detected",
            )
        )
    ).scalar_one()
    return len(gap_ids), int(kept)


async def insert_gap(
    uow: UnitOfWork,
    *,
    gap_id: UUID,
    opportunity_id: UUID,
    title: str,
    category: str,
    trigger: dict[str, Any],
    why_it_matters: str,
    impact: str,
    impact_basis: str,
    detection_id: UUID,
    requirements: list[tuple[UUID, int]],
    question_id: UUID,
    question_text: str,
    question_topic: str,
) -> None:
    """An `open`, `detected` Gap, its Requirement links `(id, version)` and its `drafted`
    Clarification Question."""
    await uow.session.execute(
        insert(GapRow).values(
            id=gap_id,
            opportunity_id=opportunity_id,
            title=title,
            category=category,
            trigger=trigger,
            why_it_matters=why_it_matters,
            impact=impact,
            impact_basis=impact_basis,
            origin="detected",
            status="open",
            detection_id=detection_id,
            row_version=1,
        )
    )
    await uow.session.execute(
        insert(GapRequirementRow),
        [
            {"gap_id": gap_id, "requirement_id": rid, "requirement_version": version}
            for rid, version in requirements
        ],
    )
    await uow.session.execute(
        insert(QuestionRow).values(
            id=question_id,
            gap_id=gap_id,
            text=question_text,
            topic=question_topic,
            status="drafted",
            row_version=1,
        )
    )


# --- mandatory Gaps (Story 4.2) -------------------------------------------------------------

MANDATORY = "mandatory_checklist"


def _checklist_id() -> ColumnElement[str]:
    return cast(ColumnElement[str], GapRow.trigger["checklist_id"].astext)


def _item_id() -> ColumnElement[str]:
    return cast(ColumnElement[str], GapRow.trigger["item_id"].astext)


async def mandatory_keys(uow: UnitOfWork, opportunity_id: UUID) -> set[tuple[UUID, UUID]]:
    """(Checklist id, item id) of each of the Opportunity's mandatory Gaps, in any status."""
    rows = await uow.session.execute(
        select(_checklist_id(), _item_id()).where(
            GapRow.opportunity_id == opportunity_id, GapRow.origin == MANDATORY
        )
    )
    return {(UUID(checklist_id), UUID(item_id)) for checklist_id, item_id in rows.all()}


async def insert_mandatory_gap(
    uow: UnitOfWork,
    *,
    gap_id: UUID,
    opportunity_id: UUID,
    title: str,
    category: str,
    trigger: dict[str, Any],
    why_it_matters: str,
    why_entry_id: UUID | None,
    impact: str,
    impact_basis: str,
    detection_id: UUID,
    question_id: UUID,
    question_text: str,
    question_topic: str,
) -> bool:
    """An `open`, `mandatory_checklist` Gap (no Requirement links) and its `drafted`,
    `from_checklist` question, unless the Opportunity already has a mandatory Gap for the
    same Checklist item in any status (`uq_gaps_gaps_mandatory_item`): then nothing is
    written. Whether it was inserted."""
    inserted = (
        await uow.session.execute(
            pg_insert(GapRow)
            .values(
                id=gap_id,
                opportunity_id=opportunity_id,
                title=title,
                category=category,
                trigger=trigger,
                why_it_matters=why_it_matters,
                why_entry_id=why_entry_id,
                impact=impact,
                impact_basis=impact_basis,
                origin=MANDATORY,
                status="open",
                detection_id=detection_id,
                checklist_applies=True,
                row_version=1,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    GapRow.opportunity_id,
                    text("(trigger ->> 'checklist_id')"),
                    text("(trigger ->> 'item_id')"),
                ],
                index_where=text("origin = 'mandatory_checklist'"),
            )
            .returning(GapRow.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        return False
    await uow.session.execute(
        insert(QuestionRow).values(
            id=question_id,
            gap_id=gap_id,
            text=question_text,
            topic=question_topic,
            status="drafted",
            from_checklist=True,
            row_version=1,
        )
    )
    return True


async def set_checklist_applies(
    uow: UnitOfWork, opportunity_id: UUID, applies: AbstractSet[tuple[UUID, UUID]]
) -> int:
    """Set `checklist_applies` on each of the Opportunity's mandatory Gaps, whatever their
    status (a settled one may be reopened later): true iff
    its (Checklist id, item id) is in `applies`. Only Gaps whose flag changes are written
    (their `row_version` is left alone: the flag is derived, not edited). How many changed."""
    rows = await uow.session.execute(
        select(GapRow.id, _checklist_id(), _item_id(), GapRow.checklist_applies).where(
            GapRow.opportunity_id == opportunity_id,
            GapRow.origin == MANDATORY,
        )
    )
    flip_on: list[UUID] = []
    flip_off: list[UUID] = []
    for gap_id, checklist_id, item_id, current in rows.all():
        wanted = (UUID(checklist_id), UUID(item_id)) in applies
        if wanted != current:
            (flip_on if wanted else flip_off).append(gap_id)
    for ids, value in ((flip_on, True), (flip_off, False)):
        if ids:
            await uow.session.execute(
                update(GapRow)
                .where(GapRow.id.in_(ids))
                .values(checklist_applies=value)
                .execution_options(synchronize_session=False)
            )
    return len(flip_on) + len(flip_off)


def _gap(row: GapRow) -> GapRecord:
    return GapRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        title=row.title,
        category=row.category,
        trigger=row.trigger,
        why_it_matters=row.why_it_matters,
        impact=row.impact,
        impact_basis=row.impact_basis,
        origin=row.origin,
        status=row.status,
        converted_to=row.converted_to,
        row_version=row.row_version,
        created_at=row.created_at,
        dismiss_reason_kind=row.dismiss_reason_kind,
        dismiss_note=row.dismiss_note,
        dismissed_by=row.dismissed_by,
        dismissed_at=row.dismissed_at,
        changed_by=row.changed_by,
        touched_by_human=row.touched_by_human,
        answered_on=row.answered_on,
        answered_by=row.answered_by,
        answer_passage_id=row.answer_passage_id,
        checklist_applies=row.checklist_applies,
        why_entry_id=row.why_entry_id,
    )


async def gaps_in(uow: UnitOfWork, opportunity_id: UUID, status: str) -> list[GapRecord]:
    """The Opportunity's Gaps in `status`, oldest first (the caller ranks them)."""
    rows = await uow.session.execute(
        select(GapRow)
        .where(GapRow.opportunity_id == opportunity_id, GapRow.status == status)
        .order_by(GapRow.created_at, GapRow.id)
    )
    return [_gap(row) for row in rows.scalars()]


async def open_gaps(uow: UnitOfWork, opportunity_id: UUID) -> list[GapRecord]:
    """The Opportunity's `open` Gaps, oldest first (the caller ranks them)."""
    return await gaps_in(uow, opportunity_id, "open")


async def open_counts(uow: UnitOfWork, opportunity_ids: list[UUID]) -> dict[UUID, int]:
    """How many `open` Gaps each of these Opportunities has, in one query; Opportunities
    with none are left out."""
    if not opportunity_ids:
        return {}
    rows = await uow.session.execute(
        select(GapRow.opportunity_id, func.count())
        .where(GapRow.opportunity_id.in_(opportunity_ids), GapRow.status == "open")
        .group_by(GapRow.opportunity_id)
    )
    return {opportunity_id: int(count) for opportunity_id, count in rows.all()}


async def gaps_by_id(
    uow: UnitOfWork, opportunity_id: UUID, gap_ids: list[UUID]
) -> dict[UUID, GapRecord]:
    """These Gaps of the Opportunity, whatever their status."""
    if not gap_ids:
        return {}
    rows = await uow.session.execute(
        select(GapRow).where(GapRow.opportunity_id == opportunity_id, GapRow.id.in_(gap_ids))
    )
    return {row.id: _gap(row) for row in rows.scalars()}


async def settled_keys(uow: UnitOfWork, opportunity_id: UUID) -> list[tuple[str, str]]:
    """The category and title of each of the Opportunity's `dismissed` (Story 4.4) and
    `answered` (Story 4.7) Gaps."""
    rows = await uow.session.execute(
        select(GapRow.category, GapRow.title).where(
            GapRow.opportunity_id == opportunity_id,
            GapRow.status.in_(("dismissed", "answered")),
        )
    )
    return [(category, title) for category, title in rows.all()]


async def update_gap(
    uow: UnitOfWork,
    gap_id: UUID,
    *,
    expected_row_version: int,
    from_status: str,
    status: str,
    impact: str,
    dismiss_reason_kind: str | None,
    dismiss_note: str | None,
    dismissed_by: UUID | None,
    dismissed_at: datetime | None,
    touched_by_human: bool,
    changed_by: UUID,
    answered_on: date | None = None,
    answered_by: UUID | None = None,
    answer_passage_id: UUID | None = None,
) -> GapRecord | None:
    """Write the Gap's new state if it is still at `expected_row_version` and in
    `from_status` (a Gap converted by `estimates` meanwhile doesn't take the gaps lock),
    bumping it; None (and no change) otherwise."""
    changed = (
        await uow.session.execute(
            update(GapRow)
            .where(
                GapRow.id == gap_id,
                GapRow.row_version == expected_row_version,
                GapRow.status == from_status,
            )
            .values(
                status=status,
                impact=impact,
                dismiss_reason_kind=dismiss_reason_kind,
                dismiss_note=dismiss_note,
                dismissed_by=dismissed_by,
                dismissed_at=dismissed_at,
                touched_by_human=touched_by_human,
                changed_by=changed_by,
                answered_on=answered_on,
                answered_by=answered_by,
                answer_passage_id=answer_passage_id,
                row_version=GapRow.row_version + 1,
            )
            .returning(GapRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_gap(uow, gap_id)


async def insert_history(
    uow: UnitOfWork,
    *,
    history_id: UUID,
    gap_id: UUID,
    kind: str,
    actor_id: UUID | None,
    at: datetime | None = None,
    old_impact: str | None = None,
    new_impact: str | None = None,
    reason_kind: str | None = None,
    reason: str | None = None,
) -> None:
    """Append one entry to the Gap's history; `at` defaults to the transaction's time."""
    values: dict[str, object] = {
        "id": history_id,
        "gap_id": gap_id,
        "kind": kind,
        "actor_id": actor_id,
        "old_impact": old_impact,
        "new_impact": new_impact,
        "reason_kind": reason_kind,
        "reason": reason,
    }
    if at is not None:
        values["at"] = at
    await uow.session.execute(insert(GapHistoryRow).values(**values))


async def history_for(uow: UnitOfWork, gap_ids: list[UUID]) -> dict[UUID, list[GapHistoryRecord]]:
    """Each Gap's history, oldest first."""
    if not gap_ids:
        return {}
    rows = await uow.session.execute(
        select(GapHistoryRow)
        .where(GapHistoryRow.gap_id.in_(gap_ids))
        .order_by(GapHistoryRow.at, GapHistoryRow.id)
    )
    found: dict[UUID, list[GapHistoryRecord]] = {}
    for row in rows.scalars():
        found.setdefault(row.gap_id, []).append(
            GapHistoryRecord(
                id=row.id,
                gap_id=row.gap_id,
                kind=row.kind,
                actor_id=row.actor_id,
                at=row.at,
                old_impact=row.old_impact,
                new_impact=row.new_impact,
                reason_kind=row.reason_kind,
                reason=row.reason,
            )
        )
    return found


async def irrelevance_counts(uow: UnitOfWork, opportunity_id: UUID | None) -> tuple[int, int]:
    """Detected Gaps not superseded, and those dismissed as `not_relevant`, of the
    Opportunity (or of every Opportunity)."""
    statement = select(
        func.count().filter(GapRow.status != "superseded"),
        func.count().filter(
            GapRow.status == "dismissed", GapRow.dismiss_reason_kind == "not_relevant"
        ),
    ).where(GapRow.origin == "detected")
    if opportunity_id is not None:
        statement = statement.where(GapRow.opportunity_id == opportunity_id)
    raised, dismissed = (await uow.session.execute(statement)).one()
    return int(raised), int(dismissed)


async def get_gap(uow: UnitOfWork, gap_id: UUID) -> GapRecord | None:
    row = (
        await uow.session.execute(
            select(GapRow).where(GapRow.id == gap_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _gap(row)


async def convert_gap(uow: UnitOfWork, gap_id: UUID, *, converted_to: str) -> GapRecord | None:
    """Mark the Gap `converted` to `converted_to` if it is `open`; None (and no change)
    otherwise."""
    changed = (
        await uow.session.execute(
            update(GapRow)
            .where(GapRow.id == gap_id, GapRow.status == "open")
            .values(
                status="converted",
                converted_to=converted_to,
                row_version=GapRow.row_version + 1,
            )
            .returning(GapRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_gap(uow, gap_id)


async def links_for(uow: UnitOfWork, gap_ids: list[UUID]) -> list[GapLinkRecord]:
    if not gap_ids:
        return []
    rows = await uow.session.execute(
        select(GapRequirementRow).where(GapRequirementRow.gap_id.in_(gap_ids))
    )
    return [
        GapLinkRecord(
            gap_id=row.gap_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
        )
        for row in rows.scalars()
    ]


def _question(row: QuestionRow) -> QuestionRecord:
    return QuestionRecord(
        id=row.id,
        gap_id=row.gap_id,
        text=row.text,
        topic=row.topic,
        status=row.status,
        status_changed_at=row.status_changed_at,
        row_version=row.row_version,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        edited_by_human=row.edited_by_human,
        changed_by=row.changed_by,
        sent_on=row.sent_on,
        sent_by=row.sent_by,
        answered_on=row.answered_on,
        answered_by=row.answered_by,
        answer_passage_id=row.answer_passage_id,
        from_checklist=row.from_checklist,
    )


async def questions_for(uow: UnitOfWork, gap_ids: list[UUID]) -> dict[UUID, QuestionRecord]:
    if not gap_ids:
        return {}
    rows = await uow.session.execute(
        select(QuestionRow)
        .where(QuestionRow.gap_id.in_(gap_ids))
        .execution_options(populate_existing=True)
    )
    return {row.gap_id: _question(row) for row in rows.scalars()}


async def get_question(
    uow: UnitOfWork, opportunity_id: UUID, question_id: UUID
) -> tuple[QuestionRecord, GapRecord] | None:
    """The question with its Gap, if the Gap belongs to the Opportunity."""
    found = (
        await uow.session.execute(
            select(QuestionRow, GapRow)
            .join(GapRow, GapRow.id == QuestionRow.gap_id)
            .where(QuestionRow.id == question_id, GapRow.opportunity_id == opportunity_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if found is None:
        return None
    question, gap = found
    return _question(question), _gap(gap)


async def drafted_questions_of_open_gaps(
    uow: UnitOfWork, opportunity_id: UUID
) -> list[QuestionRecord]:
    """The `drafted` questions of the Opportunity's `open` Gaps, oldest Gap first."""
    rows = await uow.session.execute(
        select(QuestionRow)
        .join(GapRow, GapRow.id == QuestionRow.gap_id)
        .where(
            GapRow.opportunity_id == opportunity_id,
            GapRow.status == "open",
            QuestionRow.status == "drafted",
        )
        .order_by(GapRow.created_at, GapRow.id)
        .execution_options(populate_existing=True)
    )
    return [_question(row) for row in rows.scalars()]


async def questions_of_open_gaps(
    uow: UnitOfWork, opportunity_id: UUID, status: str
) -> list[tuple[QuestionRecord, GapRecord]]:
    """The questions in `status` of the Opportunity's `open` Gaps, with their Gaps, oldest
    Gap first (the caller ranks them)."""
    found = await uow.session.execute(
        select(QuestionRow, GapRow)
        .join(GapRow, GapRow.id == QuestionRow.gap_id)
        .where(
            GapRow.opportunity_id == opportunity_id,
            GapRow.status == "open",
            QuestionRow.status == status,
        )
        .order_by(GapRow.created_at, GapRow.id)
        .execution_options(populate_existing=True)
    )
    return [(_question(question), _gap(gap)) for question, gap in found.all()]


async def update_question(
    uow: UnitOfWork,
    question_id: UUID,
    *,
    expected_row_version: int,
    text_: str,
    topic: str,
    status: str,
    approved_by: UUID | None,
    approved_at: datetime | None,
    edited_by_human: bool,
    changed_by: UUID,
    status_changed_at: datetime | None,
    sent_on: date | None = None,
    sent_by: UUID | None = None,
    answered_on: date | None = None,
    answered_by: UUID | None = None,
    answer_passage_id: UUID | None = None,
) -> QuestionRecord | None:
    """Write the question's new state if it is still at `expected_row_version` and its Gap
    is still `open` (a Gap converted by `estimates` meanwhile doesn't take the gaps lock),
    bumping it; None (and no change) otherwise. `status_changed_at` is set when given (a status
    change)."""
    values: dict[str, object] = {
        "text": text_,
        "topic": topic,
        "status": status,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "edited_by_human": edited_by_human,
        "changed_by": changed_by,
        "sent_on": sent_on,
        "sent_by": sent_by,
        "answered_on": answered_on,
        "answered_by": answered_by,
        "answer_passage_id": answer_passage_id,
        "row_version": QuestionRow.row_version + 1,
    }
    if status_changed_at is not None:
        values["status_changed_at"] = status_changed_at
    changed = (
        await uow.session.execute(
            update(QuestionRow)
            .where(
                QuestionRow.id == question_id,
                QuestionRow.row_version == expected_row_version,
                select(GapRow.id)
                .where(GapRow.id == QuestionRow.gap_id, GapRow.status == "open")
                .exists(),
            )
            .values(**values)
            .returning(QuestionRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    if changed is None:
        return None
    row = (
        await uow.session.execute(
            select(QuestionRow)
            .where(QuestionRow.id == question_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _question(row)


async def questions_open_to_answer(
    uow: UnitOfWork, opportunity_id: UUID
) -> list[tuple[QuestionRecord, GapRecord]]:
    """The `sent` and `unanswered` questions of the Opportunity's `open` Gaps, with their
    Gaps, oldest Gap first (Story 4.7)."""
    found = await uow.session.execute(
        select(QuestionRow, GapRow)
        .join(GapRow, GapRow.id == QuestionRow.gap_id)
        .where(
            GapRow.opportunity_id == opportunity_id,
            GapRow.status == "open",
            QuestionRow.status.in_(OPEN_TO_ANSWER_STATUSES),
        )
        .order_by(GapRow.created_at, GapRow.id)
        .execution_options(populate_existing=True)
    )
    return [(_question(question), _gap(gap)) for question, gap in found.all()]


# --- answer suggestions (Story 4.7) ---------------------------------------------------------


def _match(row: AnswerMatchRow) -> AnswerMatchRecord:
    return AnswerMatchRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        question_id=row.question_id,
        passage_id=row.passage_id,
        injection_suspected=row.injection_suspected,
        status=row.status,
        row_version=row.row_version,
        created_at=row.created_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )


async def insert_match(
    uow: UnitOfWork,
    *,
    match_id: UUID,
    opportunity_id: UUID,
    question_id: UUID,
    passage_id: UUID,
    injection_suspected: bool,
) -> bool:
    """A `suggested` match, unless the (question, passage) pair is already known in any
    status (a rejected pair never returns). Whether it was inserted."""
    inserted = (
        await uow.session.execute(
            pg_insert(AnswerMatchRow)
            .values(
                id=match_id,
                opportunity_id=opportunity_id,
                question_id=question_id,
                passage_id=passage_id,
                injection_suspected=injection_suspected,
                status="suggested",
                row_version=1,
            )
            .on_conflict_do_nothing(index_elements=["question_id", "passage_id"])
            .returning(AnswerMatchRow.id)
        )
    ).scalar_one_or_none()
    return inserted is not None


async def known_match_pairs(uow: UnitOfWork, question_ids: list[UUID]) -> set[tuple[UUID, UUID]]:
    """The (question, passage) pairs already matched for these questions, in any status."""
    if not question_ids:
        return set()
    rows = await uow.session.execute(
        select(AnswerMatchRow.question_id, AnswerMatchRow.passage_id).where(
            AnswerMatchRow.question_id.in_(question_ids)
        )
    )
    return {(question_id, passage_id) for question_id, passage_id in rows.all()}


async def suggested_matches(uow: UnitOfWork, question_ids: list[UUID]) -> list[AnswerMatchRecord]:
    """The `suggested` matches of these questions, oldest first."""
    if not question_ids:
        return []
    rows = await uow.session.execute(
        select(AnswerMatchRow)
        .where(AnswerMatchRow.question_id.in_(question_ids), AnswerMatchRow.status == "suggested")
        .order_by(AnswerMatchRow.created_at, AnswerMatchRow.id)
        .execution_options(populate_existing=True)
    )
    return [_match(row) for row in rows.scalars()]


async def get_match(
    uow: UnitOfWork, opportunity_id: UUID, match_id: UUID
) -> AnswerMatchRecord | None:
    """The match with this id, if it belongs to the Opportunity."""
    row = (
        await uow.session.execute(
            select(AnswerMatchRow)
            .where(AnswerMatchRow.id == match_id, AnswerMatchRow.opportunity_id == opportunity_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _match(row)


async def decide_match(
    uow: UnitOfWork,
    match_id: UUID,
    *,
    expected_row_version: int,
    status: str,
    decided_by: UUID,
) -> bool:
    """Move a `suggested` match still at `expected_row_version` to `status` (`confirmed` or
    `rejected`) with who decided, and now. False (and no change) otherwise."""
    result = await uow.session.execute(
        update(AnswerMatchRow)
        .where(
            AnswerMatchRow.id == match_id,
            AnswerMatchRow.status == "suggested",
            AnswerMatchRow.row_version == expected_row_version,
        )
        .values(
            status=status,
            decided_by=decided_by,
            decided_at=func.now(),
            row_version=AnswerMatchRow.row_version + 1,
        )
        .returning(AnswerMatchRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


async def supersede_matches(uow: UnitOfWork, question_id: UUID) -> int:
    """Mark the question's `suggested` matches `superseded` (it was answered); how many."""
    result = await uow.session.execute(
        update(AnswerMatchRow)
        .where(AnswerMatchRow.question_id == question_id, AnswerMatchRow.status == "suggested")
        .values(status="superseded", row_version=AnswerMatchRow.row_version + 1)
        .returning(AnswerMatchRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())
