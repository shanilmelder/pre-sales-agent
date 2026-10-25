"""The in-app channel (Story 9.2): an item is a `notifications_notifications` row, read on
`/inbox`."""

from app.modules.notifications.adapters import repository as repo
from app.modules.notifications.domain.notifications import ChannelName, NewNotification
from app.platform.uow import UnitOfWork


class InAppChannel:
    """`Channel` adapter: insert the row once per dedupe key."""

    name = ChannelName.IN_APP

    async def deliver(self, uow: UnitOfWork, item: NewNotification) -> bool:
        return await repo.insert_once(uow, item, self.name)
