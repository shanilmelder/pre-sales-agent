"""Inbox items (Story 9.2): kinds, groups, the summary rule and the delivery channel port.
Pure, no I/O.

An item tells one recipient that something on an Opportunity needs them (a Review Request, a
reminder, a run waiting for a decision, an escalated Conflict) or changed (a cancelled
request). Its `dedupe_key` makes every producer idempotent: a rerun, a back-fill or a later
live insert with the same key writes nothing.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

SUMMARY_MAX = 300
"""Characters (code points) a summary may hold; longer ones are cut with an ellipsis."""
PAGE_SIZE = 25


class NotificationKind(StrEnum):
    REVIEW_REQUESTED = "review_requested"
    REVIEW_REMINDER = "review_reminder"
    REVIEW_CANCELLED = "review_cancelled"
    RUN_WAITING = "run_waiting"
    CONFLICT_ESCALATED = "conflict_escalated"


class ChannelName(StrEnum):
    IN_APP = "in_app"


class InboxGroup(StrEnum):
    REVIEWS = "reviews"
    CHALLENGES = "challenges"
    WAITING = "waiting"
    UPDATES = "updates"


GROUP_ORDER: tuple[InboxGroup, ...] = (
    InboxGroup.REVIEWS,
    InboxGroup.CHALLENGES,
    InboxGroup.WAITING,
    InboxGroup.UPDATES,
)
"""The Inbox lists its groups in this order. `challenges` has no producer before Story 9.5."""

KIND_GROUP: dict[NotificationKind, InboxGroup] = {
    NotificationKind.REVIEW_REQUESTED: InboxGroup.REVIEWS,
    NotificationKind.REVIEW_REMINDER: InboxGroup.REVIEWS,
    NotificationKind.RUN_WAITING: InboxGroup.WAITING,
    NotificationKind.CONFLICT_ESCALATED: InboxGroup.WAITING,
    NotificationKind.REVIEW_CANCELLED: InboxGroup.UPDATES,
}


def group_rank(kind: NotificationKind) -> int:
    return GROUP_ORDER.index(KIND_GROUP[kind])


def clean_summary(raw: str) -> str:
    """The trimmed, single-line summary, cut to `SUMMARY_MAX` with an ellipsis."""
    text = " ".join(raw.split())
    if len(text) <= SUMMARY_MAX:
        return text
    return text[: SUMMARY_MAX - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class NewNotification:
    """One item to deliver. `subject_*` names what it is about (e.g. a Review Request at a
    version); `summary` is built from ids and glossary terms only."""

    id: UUID
    recipient_id: UUID
    kind: NotificationKind
    opportunity_id: UUID | None
    subject_type: str
    subject_id: UUID
    subject_version: int | None
    summary: str
    dedupe_key: str


class Channel(Protocol):
    """Where an item goes (the port; Epic 11 adds Teams and email beside in-app). `deliver`
    runs inside the producer's Unit of Work and returns whether it delivered (False when
    an item with the same dedupe key was already delivered)."""

    name: ChannelName

    async def deliver(self, uow: "UnitOfWork", item: NewNotification) -> bool: ...
