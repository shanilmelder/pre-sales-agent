"""The `notifications` module (Story 9.2): Inbox items.

Producers (`reviews`, `workflows`, `conflicts`) create items with `notify(uow, ...)` inside
their own Unit of Work; each item goes out through a `Channel` (R1: only the in-app channel,
a `notifications_notifications` row). People read their own items on `/inbox`, mark them
read and see an unread count. Each item's subject status is read live from its owning
module, so an item whose subject is no longer open says so and has no link.

Other modules use it only through `application/public.py`.
"""
