"""Persistence for Review Requests (Story 9.1). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select, update

from app.modules.reviews.adapters.models import ReviewRequestRow
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


@dataclass(frozen=True, slots=True)
class NewRequest:
    id: UUID
    review_type: str
    target_kind: str
    target_id: UUID
    target_version: int
    reviewer_id: UUID


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
