"""`notify` (Story 9.2): create an Inbox item inside the producer's Unit of Work.

Idempotent by `dedupe_key`: the in-app channel inserts with `ON CONFLICT (dedupe_key) DO
NOTHING`, and only a written item goes to any further channel (none in R1; Epic 11 adds
Teams and email here without changing callers). Summaries are built by the producer from ids
and glossary terms only, never message text or model output; logs carry ids and the kind.
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notifications.adapters.in_app import InAppChannel
from app.modules.notifications.domain.notifications import (
    Channel,
    NewNotification,
    NotificationKind,
    clean_summary,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_APP: Channel = InAppChannel()
EXTRA_CHANNELS: Sequence[Channel] = ()
"""Channels an item also goes to once written in-app (Epic 11)."""
_log = get_logger(__name__)


async def notify(
    uow: UnitOfWork,
    *,
    recipient_id: UUID,
    kind: NotificationKind,
    opportunity_id: UUID | None,
    subject_type: str,
    subject_id: UUID,
    subject_version: int | None,
    summary: str,
    dedupe_key: str,
) -> bool:
    """Create the item unless one with `dedupe_key` exists; whether one was written."""
    item = NewNotification(
        id=new_id(),
        recipient_id=recipient_id,
        kind=NotificationKind(kind),
        opportunity_id=opportunity_id,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_version=subject_version,
        summary=clean_summary(summary),
        dedupe_key=dedupe_key,
    )
    written = await IN_APP.deliver(uow, item)
    if written:
        for channel in EXTRA_CHANNELS:
            await channel.deliver(uow, item)
        _log.info(
            "notifications.created",
            extra={
                "notification_id": str(item.id),
                "kind": item.kind.value,
                "recipient_id": str(recipient_id),
                "opportunity_id": None if opportunity_id is None else str(opportunity_id),
            },
        )
    return written
