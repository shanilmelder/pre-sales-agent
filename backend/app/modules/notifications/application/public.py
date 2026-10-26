"""notifications' public API (Story 9.2). Other modules import notifications only from here.

- Producers (`reviews` on a Review Request's create, cancel and reminder; `workflows` when a
  run waits on a decision; `conflicts` on an escalation): `notify` in their own Unit of
  Work, with a `NotificationKind`.
- The routes: `list_inbox`, `unread_count`, `mark_read`, `mark_all_read`.
"""

from app.modules.notifications.application.inbox import (
    list_inbox,
    mark_all_read,
    mark_read,
    unread_count,
)
from app.modules.notifications.application.models import (
    InboxItem,
    InboxPage,
    MarkedRead,
    UnreadCount,
)
from app.modules.notifications.application.notify import notify
from app.modules.notifications.domain.notifications import (
    PAGE_SIZE,
    SUMMARY_MAX,
    InboxGroup,
    NotificationKind,
)

__all__ = [
    "PAGE_SIZE",
    "SUMMARY_MAX",
    "InboxGroup",
    "InboxItem",
    "InboxPage",
    "MarkedRead",
    "NotificationKind",
    "UnreadCount",
    "list_inbox",
    "mark_all_read",
    "mark_read",
    "notify",
    "unread_count",
]
