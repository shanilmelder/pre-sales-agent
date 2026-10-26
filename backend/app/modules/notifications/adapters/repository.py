"""Persistence for Inbox items (Story 9.2). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.modules.notifications.adapters.models import NotificationRow
from app.modules.notifications.domain.notifications import (
    KIND_GROUP,
    ChannelName,
    NewNotification,
    group_rank,
)
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    id: UUID
    recipient_id: UUID
    kind: str
    opportunity_id: UUID | None
    subject_type: str
    subject_id: UUID
    subject_version: int | None
    summary: str
    read_at: datetime | None
    created_at: datetime


def _record(row: NotificationRow) -> NotificationRecord:
    return NotificationRecord(
        id=row.id,
        recipient_id=row.recipient_id,
        kind=row.kind,
        opportunity_id=row.opportunity_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_version=row.subject_version,
        summary=row.summary,
        read_at=row.read_at,
        created_at=row.created_at,
    )


async def insert_once(uow: UnitOfWork, item: NewNotification, channel: ChannelName) -> bool:
    """Insert the item unless one with its dedupe key exists; whether a row was written."""
    written = await uow.session.execute(
        insert(NotificationRow)
        .values(
            id=item.id,
            recipient_id=item.recipient_id,
            kind=item.kind.value,
            opportunity_id=item.opportunity_id,
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            subject_version=item.subject_version,
            summary=item.summary,
            dedupe_key=item.dedupe_key,
            channel=channel.value,
        )
        .on_conflict_do_nothing(index_elements=[NotificationRow.dedupe_key])
        .returning(NotificationRow.id)
    )
    return written.scalar_one_or_none() is not None


_GROUP_RANK = case(
    {kind.value: group_rank(kind) for kind in KIND_GROUP}, value=NotificationRow.kind, else_=99
)


async def page_of(
    uow: UnitOfWork, recipient_id: UUID, *, page: int, page_size: int
) -> tuple[list[NotificationRecord], int]:
    """One page of the recipient's items, by group then newest first, and how many there
    are."""
    total = (
        await uow.session.execute(
            select(func.count())
            .select_from(NotificationRow)
            .where(NotificationRow.recipient_id == recipient_id)
        )
    ).scalar_one()
    rows = await uow.session.execute(
        select(NotificationRow)
        .where(NotificationRow.recipient_id == recipient_id)
        .order_by(_GROUP_RANK, NotificationRow.created_at.desc(), NotificationRow.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .execution_options(populate_existing=True)
    )
    return [_record(row) for row in rows.scalars()], int(total)


async def unread_count(uow: UnitOfWork, recipient_id: UUID) -> int:
    found = await uow.session.execute(
        select(func.count())
        .select_from(NotificationRow)
        .where(NotificationRow.recipient_id == recipient_id, NotificationRow.read_at.is_(None))
    )
    return int(found.scalar_one())


async def get(uow: UnitOfWork, notification_id: UUID) -> NotificationRecord | None:
    row = (
        await uow.session.execute(
            select(NotificationRow)
            .where(NotificationRow.id == notification_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _record(row)


async def mark_read(uow: UnitOfWork, recipient_id: UUID, notification_id: UUID) -> bool:
    """Mark the recipient's item read (kept as it is when already read); whether the item is
    theirs."""
    changed = await uow.session.execute(
        update(NotificationRow)
        .where(NotificationRow.id == notification_id, NotificationRow.recipient_id == recipient_id)
        .values(read_at=func.coalesce(NotificationRow.read_at, func.now()))
        .returning(NotificationRow.id)
        .execution_options(synchronize_session=False)
    )
    return changed.scalar_one_or_none() is not None


async def mark_all_read(uow: UnitOfWork, recipient_id: UUID) -> int:
    """Mark every unread item of the recipient read; how many changed."""
    changed = await uow.session.execute(
        update(NotificationRow)
        .where(NotificationRow.recipient_id == recipient_id, NotificationRow.read_at.is_(None))
        .values(read_at=func.now())
        .returning(NotificationRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(changed.all())
