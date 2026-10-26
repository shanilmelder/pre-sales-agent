"""Persistence for Review Requests (Story 9.1), their Review Decisions (Story 9.3) and their
replies (Story 9.4). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update

from app.modules.reviews.adapters.models import (
    ReviewDecisionRow,
    ReviewReplyRow,
    ReviewRequestRow,
)
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class RequestRecord:
    id: UUID
    opportunity_id: UUID
    review_type: str
    target_kind: str
    target_id: UUID
    target_version: int
    estimate_version_id: UUID
    reviewer_id: UUID
    requested_by: UUID
    message: str | None
    status: str
    cancel_reason: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    linked_request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NewRequest:
    id: UUID
    review_type: str
    target_kind: str
    target_id: UUID
    target_version: int
    reviewer_id: UUID
    linked_request_id: UUID | None = None


def _record(row: ReviewRequestRow) -> RequestRecord:
    return RequestRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        review_type=row.review_type,
        target_kind=row.target_kind,
        target_id=row.target_id,
        target_version=row.target_version,
        estimate_version_id=row.estimate_version_id,
        reviewer_id=row.reviewer_id,
        requested_by=row.requested_by,
        message=row.message,
        status=row.status,
        cancel_reason=row.cancel_reason,
        row_version=row.row_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        linked_request_id=row.linked_request_id,
    )


async def insert_requests(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    estimate_version_id: UUID,
    requested_by: UUID,
    message: str | None,
    requests: list[NewRequest],
) -> None:
    """`pending` requests, one per entry."""
    await uow.session.execute(
        insert(ReviewRequestRow),
        [
            {
                "id": r.id,
                "opportunity_id": opportunity_id,
                "review_type": r.review_type,
                "target_kind": r.target_kind,
                "target_id": r.target_id,
                "target_version": r.target_version,
                "estimate_version_id": estimate_version_id,
                "reviewer_id": r.reviewer_id,
                "requested_by": requested_by,
                "message": message,
                "status": "pending",
                "row_version": 1,
                "linked_request_id": r.linked_request_id,
            }
            for r in requests
        ],
    )


async def get(
    uow: UnitOfWork, request_id: UUID, *, for_update: bool = False
) -> RequestRecord | None:
    statement = (
        select(ReviewRequestRow)
        .where(ReviewRequestRow.id == request_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _record(row)


async def of_ids(uow: UnitOfWork, request_ids: list[UUID]) -> list[RequestRecord]:
    """These requests, in the order given."""
    rows = await uow.session.execute(
        select(ReviewRequestRow)
        .where(ReviewRequestRow.id.in_(request_ids))
        .execution_options(populate_existing=True)
    )
    found = {row.id: _record(row) for row in rows.scalars()}
    return [found[i] for i in request_ids if i in found]


async def of_version(
    uow: UnitOfWork, estimate_version_id: UUID, *, statuses: tuple[str, ...] | None = None
) -> list[RequestRecord]:
    """The requests counting towards the version (in these `statuses`, if given), oldest
    first."""
    statement = select(ReviewRequestRow).where(
        ReviewRequestRow.estimate_version_id == estimate_version_id
    )
    if statuses is not None:
        statement = statement.where(ReviewRequestRow.status.in_(statuses))
    rows = await uow.session.execute(
        statement.order_by(ReviewRequestRow.created_at, ReviewRequestRow.id).execution_options(
            populate_existing=True
        )
    )
    return [_record(row) for row in rows.scalars()]


async def pending_duplicates(uow: UnitOfWork, candidates: list[NewRequest]) -> list[RequestRecord]:
    """The pending requests with the same reviewer, review type and target as a candidate."""
    if not candidates:
        return []
    keys = {
        (c.reviewer_id, c.review_type, c.target_kind, c.target_id, c.target_version)
        for c in candidates
    }
    rows = await uow.session.execute(
        select(ReviewRequestRow).where(
            ReviewRequestRow.status == "pending",
            ReviewRequestRow.reviewer_id.in_({k[0] for k in keys}),
            ReviewRequestRow.target_id.in_({k[3] for k in keys}),
        )
    )
    return [
        _record(row)
        for row in rows.scalars()
        if (row.reviewer_id, row.review_type, row.target_kind, row.target_id, row.target_version)
        in keys
    ]


async def has_pending_for_reviewer(
    uow: UnitOfWork, opportunity_id: UUID, reviewer_id: UUID
) -> bool:
    found = await uow.session.execute(
        select(ReviewRequestRow.id)
        .where(
            ReviewRequestRow.opportunity_id == opportunity_id,
            ReviewRequestRow.reviewer_id == reviewer_id,
            ReviewRequestRow.status == "pending",
        )
        .limit(1)
    )
    return found.first() is not None


async def has_pending_for_version(uow: UnitOfWork, estimate_version_id: UUID) -> bool:
    found = await uow.session.execute(
        select(ReviewRequestRow.id)
        .where(
            ReviewRequestRow.estimate_version_id == estimate_version_id,
            ReviewRequestRow.status == "pending",
        )
        .limit(1)
    )
    return found.first() is not None


async def set_status(
    uow: UnitOfWork,
    request_id: UUID,
    *,
    from_status: str,
    to_status: str,
    expected_row_version: int,
    cancel_reason: str | None = None,
) -> RequestRecord | None:
    """Move the request from `from_status` at `expected_row_version` to `to_status`, bumping
    `row_version`; None (and no change) otherwise."""
    changed = (
        await uow.session.execute(
            update(ReviewRequestRow)
            .where(
                ReviewRequestRow.id == request_id,
                ReviewRequestRow.status == from_status,
                ReviewRequestRow.row_version == expected_row_version,
            )
            .values(
                status=to_status,
                cancel_reason=cancel_reason,
                row_version=ReviewRequestRow.row_version + 1,
                updated_at=func.now(),
            )
            .returning(ReviewRequestRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get(uow, request_id)


async def pending_for_reminders(
    uow: UnitOfWork, interval_s: int
) -> tuple[datetime, list[RequestRecord]]:
    """The database's `now()` and the pending requests at least one interval old, oldest
    first (Story 9.2)."""
    now = (await uow.session.execute(select(func.now()))).scalar_one()
    rows = await uow.session.execute(
        select(ReviewRequestRow)
        .where(
            ReviewRequestRow.status == "pending",
            ReviewRequestRow.created_at <= now - timedelta(seconds=interval_s),
        )
        .order_by(ReviewRequestRow.created_at, ReviewRequestRow.id)
        .execution_options(populate_existing=True)
    )
    return now, [_record(row) for row in rows.scalars()]


async def reassign(
    uow: UnitOfWork, request_id: UUID, *, reviewer_id: UUID, expected_row_version: int
) -> RequestRecord | None:
    """Story 9.3 (an escalation): hand the `pending` request at `expected_row_version` to
    `reviewer_id`, bumping `row_version`; None (and no change) otherwise."""
    changed = (
        await uow.session.execute(
            update(ReviewRequestRow)
            .where(
                ReviewRequestRow.id == request_id,
                ReviewRequestRow.status == "pending",
                ReviewRequestRow.row_version == expected_row_version,
            )
            .values(
                reviewer_id=reviewer_id,
                row_version=ReviewRequestRow.row_version + 1,
                updated_at=func.now(),
            )
            .returning(ReviewRequestRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get(uow, request_id)


async def bump(
    uow: UnitOfWork, request_id: UUID, *, expected_row_version: int
) -> RequestRecord | None:
    """Story 9.3 (a decision that leaves the request `pending`): bump the `row_version` of the
    pending request at `expected_row_version`; None (and no change) otherwise."""
    changed = (
        await uow.session.execute(
            update(ReviewRequestRow)
            .where(
                ReviewRequestRow.id == request_id,
                ReviewRequestRow.status == "pending",
                ReviewRequestRow.row_version == expected_row_version,
            )
            .values(row_version=ReviewRequestRow.row_version + 1, updated_at=func.now())
            .returning(ReviewRequestRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get(uow, request_id)


# --- Review Decisions (Story 9.3) -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    id: UUID
    review_request_id: UUID
    decision: str
    reason: str | None
    decided_by: UUID
    target_version: int
    escalated_to: UUID | None
    decided_at: datetime


def _decision(row: ReviewDecisionRow) -> DecisionRecord:
    return DecisionRecord(
        id=row.id,
        review_request_id=row.review_request_id,
        decision=row.decision,
        reason=row.reason,
        decided_by=row.decided_by,
        target_version=row.target_version,
        escalated_to=row.escalated_to,
        decided_at=row.decided_at,
    )


async def insert_decision(
    uow: UnitOfWork,
    *,
    decision_id: UUID,
    review_request_id: UUID,
    decision: str,
    reason: str | None,
    decided_by: UUID,
    target_version: int,
    escalated_to: UUID | None,
) -> DecisionRecord:
    await uow.session.execute(
        insert(ReviewDecisionRow).values(
            id=decision_id,
            review_request_id=review_request_id,
            decision=decision,
            reason=reason,
            decided_by=decided_by,
            target_version=target_version,
            escalated_to=escalated_to,
        )
    )
    row = (
        await uow.session.execute(
            select(ReviewDecisionRow)
            .where(ReviewDecisionRow.id == decision_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _decision(row)


_NEWEST_FIRST = (ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())


async def decisions_of(uow: UnitOfWork, request_id: UUID) -> list[DecisionRecord]:
    """The request's decisions, newest first."""
    rows = await uow.session.execute(
        select(ReviewDecisionRow)
        .where(ReviewDecisionRow.review_request_id == request_id)
        .order_by(*_NEWEST_FIRST)
    )
    return [_decision(row) for row in rows.scalars()]


async def latest_decisions(uow: UnitOfWork, request_ids: list[UUID]) -> dict[UUID, DecisionRecord]:
    """Each of these requests' latest decision; ones with none are left out."""
    if not request_ids:
        return {}
    rows = await uow.session.execute(
        select(ReviewDecisionRow)
        .where(ReviewDecisionRow.review_request_id.in_(request_ids))
        .order_by(*_NEWEST_FIRST)
    )
    latest: dict[UUID, DecisionRecord] = {}
    for row in rows.scalars():
        latest.setdefault(row.review_request_id, _decision(row))
    return latest


async def all_approved(uow: UnitOfWork, estimate_version_id: UUID) -> bool:
    """Whether every non-cancelled request counting towards the version is `approved` (and
    there is at least one)."""
    rows = await uow.session.execute(
        select(ReviewRequestRow.status).where(
            ReviewRequestRow.estimate_version_id == estimate_version_id,
            ReviewRequestRow.status != "cancelled",
        )
    )
    statuses = list(rows.scalars())
    return bool(statuses) and all(s == "approved" for s in statuses)


# --- replies (Story 9.4) --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplyRecord:
    id: UUID
    review_request_id: UUID
    message: str
    evidence: list[dict[str, Any]]
    alternative_version_id: UUID | None
    replied_by: UUID
    replied_at: datetime


def _reply(row: ReviewReplyRow) -> ReplyRecord:
    return ReplyRecord(
        id=row.id,
        review_request_id=row.review_request_id,
        message=row.message,
        evidence=list(row.evidence or []),
        alternative_version_id=row.alternative_version_id,
        replied_by=row.replied_by,
        replied_at=row.replied_at,
    )


async def insert_reply(
    uow: UnitOfWork,
    *,
    reply_id: UUID,
    review_request_id: UUID,
    message: str,
    evidence: list[dict[str, Any]],
    alternative_version_id: UUID | None,
    replied_by: UUID,
) -> ReplyRecord:
    await uow.session.execute(
        insert(ReviewReplyRow).values(
            id=reply_id,
            review_request_id=review_request_id,
            message=message,
            evidence=evidence,
            alternative_version_id=alternative_version_id,
            replied_by=replied_by,
        )
    )
    row = (
        await uow.session.execute(
            select(ReviewReplyRow)
            .where(ReviewReplyRow.id == reply_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _reply(row)


_REPLIES_NEWEST_FIRST = (ReviewReplyRow.replied_at.desc(), ReviewReplyRow.id.desc())


async def replies_of(uow: UnitOfWork, request_id: UUID) -> list[ReplyRecord]:
    """The request's replies, newest first."""
    rows = await uow.session.execute(
        select(ReviewReplyRow)
        .where(ReviewReplyRow.review_request_id == request_id)
        .order_by(*_REPLIES_NEWEST_FIRST)
    )
    return [_reply(row) for row in rows.scalars()]


async def latest_replies(uow: UnitOfWork, request_ids: list[UUID]) -> dict[UUID, ReplyRecord]:
    """Each of these requests' latest reply; ones with none are left out."""
    if not request_ids:
        return {}
    rows = await uow.session.execute(
        select(ReviewReplyRow)
        .where(ReviewReplyRow.review_request_id.in_(request_ids))
        .order_by(*_REPLIES_NEWEST_FIRST)
    )
    latest: dict[UUID, ReplyRecord] = {}
    for row in rows.scalars():
        latest.setdefault(row.review_request_id, _reply(row))
    return latest


async def latest_alternatives(uow: UnitOfWork, request_ids: list[UUID]) -> dict[UUID, ReplyRecord]:
    """Each of these requests' latest reply that names an alternative; ones with none are left
    out."""
    if not request_ids:
        return {}
    rows = await uow.session.execute(
        select(ReviewReplyRow)
        .where(
            ReviewReplyRow.review_request_id.in_(request_ids),
            ReviewReplyRow.alternative_version_id.is_not(None),
        )
        .order_by(*_REPLIES_NEWEST_FIRST)
    )
    latest: dict[UUID, ReplyRecord] = {}
    for row in rows.scalars():
        latest.setdefault(row.review_request_id, _reply(row))
    return latest
