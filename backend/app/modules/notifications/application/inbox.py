"""The Inbox (Story 9.2): the caller's own items, the unread count and marking items read.

Everyone holding a role has `notifications.notification.read` (`ANY_ROLE_GRANTS`), and it
only ever reaches the caller's own items: another user's item id is 404, the same as an
unknown one. Only signed-in users have an Inbox (403 for agents and systems).

Each item's subject status is read live from the module that owns it (`reviews`,
`workflows`, `conflicts`), and Opportunity titles from `opportunities`, all imported lazily:
those modules import `notifications.public` to create items. When the subject is no longer
open the item has no `href` and shows its status. Story 9.3: a Review Request item is
closed for a reader who is no longer the request's reviewer (it was escalated). Story 9.4: an
outcome item is open while its request is pending, and a superseded request reads
"Superseded by v4".
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.notifications.adapters import repository as repo
from app.modules.notifications.adapters.repository import NotificationRecord
from app.modules.notifications.application.models import (
    InboxItem,
    InboxPage,
    MarkedRead,
    UnreadCount,
)
from app.modules.notifications.domain.notifications import (
    KIND_GROUP,
    PAGE_SIZE,
    NotificationKind,
)
from app.platform.errors import ForbiddenError, NotFoundError
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

REVIEW_SUBJECT = "reviews.review_request"
DECISION_SUBJECT = "workflows.decision"
CONFLICT_SUBJECT = "conflicts.conflict"
NOT_FOUND = "No Inbox item with this id."
USERS_ONLY = "Only a signed-in user has an Inbox."
DECISION_LABELS = {"open": "Waiting", "resolved": "Resolved", "cancelled": "Cancelled"}
CONFLICT_LABELS = {
    "open": "Open",
    "negotiating": "Negotiating",
    "escalated": "Escalated",
    "resolved": "Resolved",
}
CONFLICT_OPEN = frozenset({"open", "negotiating", "escalated"})
ESCALATED = "escalated"
ESCALATED_LABEL = "Escalated"
"""Story 9.3: a pending Review Request handed to another reviewer, as its earlier reviewer's
item shows it (closed: no `href`)."""
AUTHOR_SIDE_KINDS = frozenset({NotificationKind.REVIEW_OUTCOME})
"""Story 9.4: the author's outcome items, open while the request is pending whoever holds it,
never "Escalated". A `review_replied` item is the reviewer's, closed like their others once
the request is escalated away."""


def superseded_label(version: int) -> str:
    """Story 9.4: "Superseded by v4"."""
    return f"Superseded by v{version}"


_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Subject:
    status: str | None
    label: str | None
    open: bool
    href: str | None
    sender_id: UUID | None = None


def _recipient(actor: Principal) -> UUID:
    identity.authorize(actor, Action.NOTIFICATION_READ)
    user_id = actor.user_id
    if user_id is None:
        raise ForbiddenError(USERS_ONLY)
    return user_id


def _tab(opportunity_id: UUID | None, tab: str, query: str = "") -> str | None:
    return None if opportunity_id is None else f"/opportunities/{opportunity_id}/{tab}{query}"


async def _subject(uow: UnitOfWork, record: NotificationRecord) -> _Subject:
    """The subject's live status (lazy imports: the owners import this module's API)."""
    if record.subject_type == REVIEW_SUBJECT:
        from app.modules.reviews.application import public as reviews

        state = await reviews.request_status(uow, record.subject_id)
        if state is None:
            return _Subject(None, None, False, None)
        is_open = state.status == reviews.RequestStatus.PENDING
        href = _tab(record.opportunity_id, "estimate", f"?review={record.subject_id}")
        # Story 9.4: an outcome item follows the request itself, whoever holds it.
        reviewer_item = NotificationKind(record.kind) not in AUTHOR_SIDE_KINDS
        if is_open and reviewer_item and state.reviewer_id != record.recipient_id:
            # Story 9.3: escalated to someone else, so it is no longer this reader's to decide.
            return _Subject(ESCALATED, ESCALATED_LABEL, False, None, state.requested_by)
        label = reviews.STATUS_LABELS[state.status]
        if state.status == reviews.RequestStatus.SUPERSEDED and state.superseded_by is not None:
            label = superseded_label(state.superseded_by)
        return _Subject(
            state.status.value,
            label,
            is_open,
            href if is_open else None,
            state.requested_by,
        )
    if record.subject_type == DECISION_SUBJECT:
        from app.modules.workflows.application import public as workflows

        decision = await workflows.decision_status(uow, record.subject_id)
        if decision is None:
            return _Subject(None, None, False, None)
        is_open = decision == workflows.DecisionStatus.OPEN
        href = _tab(record.opportunity_id, "assessments")
        return _Subject(
            decision.value, DECISION_LABELS[decision.value], is_open, href if is_open else None
        )
    if record.subject_type == CONFLICT_SUBJECT:
        from app.modules.conflicts.application import public as conflicts

        status = await conflicts.conflict_status(uow, record.subject_id)
        if status is None:
            return _Subject(None, None, False, None)
        is_open = status in CONFLICT_OPEN
        href = _tab(record.opportunity_id, "conflicts")
        return _Subject(status, CONFLICT_LABELS.get(status), is_open, href if is_open else None)
    return _Subject(None, None, False, None)  # pragma: no cover - every producer is above


async def _items(uow: UnitOfWork, records: list[NotificationRecord]) -> list[InboxItem]:
    # Imported here: opportunities reads other modules that create items through this one.
    from app.modules.opportunities.application import public as opportunities

    subjects = [await _subject(uow, r) for r in records]
    titles = await opportunities.opportunity_titles(
        uow, {r.opportunity_id for r in records if r.opportunity_id is not None}
    )
    names = await identity.user_names(
        uow, {s.sender_id for s in subjects if s.sender_id is not None}
    )
    return [
        InboxItem(
            id=str(r.id),
            kind=NotificationKind(r.kind),
            group=KIND_GROUP[NotificationKind(r.kind)],
            summary=r.summary,
            opportunity_id=None if r.opportunity_id is None else str(r.opportunity_id),
            opportunity_title=None if r.opportunity_id is None else titles.get(r.opportunity_id),
            subject_type=r.subject_type,
            subject_id=str(r.subject_id),
            subject_version=r.subject_version,
            subject_status=s.status,
            subject_status_label=s.label,
            subject_open=s.open,
            sender=None if s.sender_id is None else names.get(s.sender_id),
            href=s.href,
            read=r.read_at is not None,
            created_at=r.created_at,
        )
        for r, s in zip(records, subjects, strict=True)
    ]


async def list_inbox(uow: UnitOfWork, actor: Principal, *, page: int = 1) -> InboxPage:
    """One page of the caller's Inbox (`PAGE_SIZE` items), by group then newest first."""
    recipient = _recipient(actor)
    records, total = await repo.page_of(uow, recipient, page=page, page_size=PAGE_SIZE)
    return InboxPage(
        items=await _items(uow, records),
        page=page,
        page_size=PAGE_SIZE,
        total=total,
        unread=await repo.unread_count(uow, recipient),
    )


async def unread_count(uow: UnitOfWork, actor: Principal) -> UnreadCount:
    return UnreadCount(unread=await repo.unread_count(uow, _recipient(actor)))


async def mark_read(uow: UnitOfWork, actor: Principal, notification_id: UUID) -> InboxItem:
    """Mark one of the caller's items read (again is a no-op); 404 for anyone else's."""
    recipient = _recipient(actor)
    if not await repo.mark_read(uow, recipient, notification_id):
        raise NotFoundError(NOT_FOUND)
    record = await repo.get(uow, notification_id)
    if record is None:  # pragma: no cover - it was just updated
        raise NotFoundError(NOT_FOUND)
    (item,) = await _items(uow, [record])
    return item


async def mark_all_read(uow: UnitOfWork, actor: Principal) -> MarkedRead:
    recipient = _recipient(actor)
    marked = await repo.mark_all_read(uow, recipient)
    _log.info(
        "notifications.all_read", extra={"recipient_id": str(recipient), "marked_count": marked}
    )
    return MarkedRead(marked=marked, unread=await repo.unread_count(uow, recipient))
