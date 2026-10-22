"""Checklist routes (Story 3.4) under `/api/v1/knowledge/checklists`. Reads: any user with a
role. Writes: engineering, PM and security reviewers and platform administrators, on any
Checklist; each write except creating takes the Checklist's `ETag` back in `If-Match`."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import (
    Checklist,
    ChecklistList,
    ChecklistVersion,
    ChecklistVersionList,
    DraftInput,
    NewChecklist,
    RetireChecklist,
)
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "The caller has no role, or (for writes) is not an engineering, PM or security "
    "reviewer or a platform administrator (`forbidden`)",
    404: "No Checklist with this id, or no such version (`not_found`)",
    409: "The Checklist is retired (`knowledge_checklist_retired`), already has a draft "
    "(`checklist_draft_exists`) or has none (`checklist_no_draft`)",
    412: "The Checklist changed since the caller read it (`row_version_mismatch`)",
    422: "A field is blank or too long, a retired or unknown Integration Type or affected "
    "area, an item id that isn't the Checklist's, a draft that can't be published yet (the "
    "`detail` is the sentence to show), an unknown field, or an id that is not a UUID "
    "(`validation_error`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}
_ETAG_HEADER = {
    "ETag": {
        "description": "The Checklist's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Checklist as last read (its `row_version`), e.g. `"3"`.',
    ),
]
_VERSION = Annotated[int, Path(ge=1, le=2_147_483_647)]


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


def _with_etag(response: Response, checklist: Checklist) -> Checklist:
    response.headers["ETag"] = etag(checklist.row_version)
    return checklist


router = APIRouter(prefix="/knowledge/checklists", tags=["knowledge"])
_WRITE = _responses(403, 404, 409, 412, 422, 428)
_OK_ETAG: dict[int | str, dict[str, Any]] = {
    200: {"description": "The Checklist", "headers": _ETAG_HEADER}
}


@router.get("", operation_id="list_knowledge_checklists", responses=_responses(403, 422))
async def list_knowledge_checklists(
    actor: CurrentPrincipal,
    uow: UoW,
    include_retired: Annotated[bool, Query(description="Include retired Checklists.")] = False,
) -> ChecklistList:
    """Checklists by name, each with its current version's items and its draft. Active only
    unless `include_retired`. Any user with a role."""
    return await knowledge.list_checklists(uow, actor, include_retired=include_retired)


@router.post(
    "",
    operation_id="create_knowledge_checklist",
    status_code=201,
    responses={
        **_responses(403, 422),
        201: {"description": "The new Checklist, with an empty draft", "headers": _ETAG_HEADER},
    },
)
async def create_knowledge_checklist(
    body: NewChecklist, actor: CurrentPrincipal, uow: UoW, response: Response
) -> Checklist:
    """Create a Checklist with a name and a domain. It has a draft and no version yet."""
    return _with_etag(response, await knowledge.create_checklist(uow, actor, body))


@router.get(
    "/{checklist_id}",
    operation_id="get_knowledge_checklist",
    responses={**_responses(403, 404, 422), **_OK_ETAG},
)
async def get_knowledge_checklist(
    checklist_id: UUID, actor: CurrentPrincipal, uow: UoW, response: Response
) -> Checklist:
    """One Checklist, retired or not. Any user with a role."""
    return _with_etag(response, await knowledge.read_checklist(uow, actor, checklist_id))


@router.get(
    "/{checklist_id}/versions",
    operation_id="list_knowledge_checklist_versions",
    responses=_responses(403, 404, 422),
)
async def list_knowledge_checklist_versions(
    checklist_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> ChecklistVersionList:
    """The published versions, newest first, with publisher and date. Any user with a role."""
    return await knowledge.read_checklist_versions(uow, actor, checklist_id)


@router.get(
    "/{checklist_id}/versions/{version}",
    operation_id="get_knowledge_checklist_version",
    responses=_responses(403, 404, 422),
)
async def get_knowledge_checklist_version(
    checklist_id: UUID, version: _VERSION, actor: CurrentPrincipal, uow: UoW
) -> ChecklistVersion:
    """One published version as published, read-only. Any user with a role."""
    return await knowledge.read_checklist_version(uow, actor, checklist_id, version)


@router.post(
    "/{checklist_id}/draft",
    operation_id="open_knowledge_checklist_draft",
    responses={**_WRITE, **_OK_ETAG},
)
async def open_knowledge_checklist_draft(
    checklist_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Checklist:
    """Start a draft from the latest published version; its items keep their ids. The
    published version stays in use until the draft is published."""
    return _with_etag(response, await knowledge.open_draft(uow, actor, checklist_id, if_match))


@router.put(
    "/{checklist_id}/draft",
    operation_id="save_knowledge_checklist_draft",
    responses={**_WRITE, **_OK_ETAG},
)
async def save_knowledge_checklist_draft(
    checklist_id: UUID,
    body: DraftInput,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Checklist:
    """Replace the whole draft. A new item (`id` null) gets a stable id."""
    checklist = await knowledge.save_draft(uow, actor, checklist_id, body, if_match)
    return _with_etag(response, checklist)


@router.post(
    "/{checklist_id}/publish",
    operation_id="publish_knowledge_checklist",
    responses={**_WRITE, **_OK_ETAG},
)
async def publish_knowledge_checklist(
    checklist_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Checklist:
    """Publish the draft as the next immutable version and clear the draft. Needs a scope
    entry (a product, the industry or an Integration Type) and at least one complete item."""
    checklist = await knowledge.publish_checklist(uow, actor, checklist_id, if_match)
    return _with_etag(response, checklist)


@router.post(
    "/{checklist_id}/retire",
    operation_id="retire_knowledge_checklist",
    responses={**_WRITE, **_OK_ETAG},
)
async def retire_knowledge_checklist(
    checklist_id: UUID,
    body: RetireChecklist,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Checklist:
    """Retire the Checklist with a reason. It no longer applies; its versions stay readable
    and its draft is discarded."""
    checklist = await knowledge.retire_checklist(uow, actor, checklist_id, body, if_match)
    return _with_etag(response, checklist)
