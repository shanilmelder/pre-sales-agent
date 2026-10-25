"""Inbox routes (Story 9.2), under `/api/v1/inbox`. The caller's own items only.

- `GET /inbox?page=`: one page of 25 items, by group then newest first;
- `GET /inbox/unread-count`;
- `POST /inbox/{notification_id}/read`: mark one item read (404 for anyone else's);
- `POST /inbox/read-all`: mark every item read.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.notifications.application import public as notifications
from app.modules.notifications.application.public import (
    InboxItem,
    InboxPage,
    MarkedRead,
    UnreadCount,
)
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

MAX_PAGE = 1_000_000
PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller holds no role, or is not a signed-in user",
    404: "No Inbox item with this id for the caller (`not_found`)",
    422: "`validation_error`: a malformed id or page",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 403, 503, *codes)
    }


router = APIRouter(prefix="/inbox", tags=["notifications"])


@router.get("", operation_id="list_inbox", responses=_responses(422))
async def list_inbox(
    actor: CurrentPrincipal,
    uow: UoW,
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
) -> InboxPage:
    """The caller's Inbox, 25 items a page: Review Requests and reminders, then Challenges,
    then what waits for the caller's input (runs and escalated Conflicts), then updates;
    newest first within each. Each item has its subject's status read now, and a link
    while the subject is still open. Also the caller's unread count."""
    return await notifications.list_inbox(uow, actor, page=page)


@router.get("/unread-count", operation_id="get_inbox_unread_count", responses=_responses())
async def get_unread_count(actor: CurrentPrincipal, uow: UoW) -> UnreadCount:
    """How many of the caller's Inbox items are unread."""
    return await notifications.unread_count(uow, actor)


@router.post("/read-all", operation_id="mark_inbox_read", responses=_responses())
async def mark_all_read(actor: CurrentPrincipal, uow: UoW) -> MarkedRead:
    """Mark every unread item of the caller read."""
    return await notifications.mark_all_read(uow, actor)


@router.post(
    "/{notification_id}/read",
    operation_id="mark_inbox_item_read",
    responses=_responses(404, 422),
)
async def mark_read(notification_id: UUID, actor: CurrentPrincipal, uow: UoW) -> InboxItem:
    """Mark one of the caller's items read (an item already read stays as it is)."""
    return await notifications.mark_read(uow, actor, notification_id)
