"""notifications' API models (Story 9.2)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.notifications.domain.notifications import InboxGroup, NotificationKind


class InboxItem(BaseModel):
    """One Inbox item. `group`: the Inbox section (`reviews`, `challenges`, `waiting`,
    `updates`); `read`: whether the caller has opened it; `subject_status` (and its label):
    the subject's status now, read live; `subject_open`: whether the subject still needs the
    caller. `href`: the web page to open it on, null once the subject is no longer open.
    `sender`: who sent it, for Review Requests."""

    id: str
    kind: NotificationKind
    group: InboxGroup
    summary: str
    opportunity_id: str | None
    opportunity_title: str | None
    subject_type: str
    subject_id: str
    subject_version: int | None
    subject_status: str | None
    subject_status_label: str | None
    subject_open: bool
    sender: str | None
    href: str | None
    read: bool
    created_at: datetime


class InboxPage(BaseModel):
    """One page of the caller's Inbox (25 items), by group then newest first, and the
    caller's unread count."""

    items: list[InboxItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    unread: int = Field(ge=0)


class UnreadCount(BaseModel):
    unread: int = Field(ge=0)


class MarkedRead(BaseModel):
    """What a mark-read changed: `marked` items now read, and the unread count left."""

    marked: int = Field(ge=0)
    unread: int = Field(ge=0)
