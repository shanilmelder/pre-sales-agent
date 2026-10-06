"""Catalogue routes (Story 3.1) under `/api/v1/catalogue/entries`. Reads: any user with a
role. Writes: platform administrators; each takes the entry's `ETag` back in `If-Match`."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import (
    CatalogueEntry,
    CatalogueList,
    CatalogueVersionList,
    EntryChanges,
    Kind,
    NewEntry,
    RetireRequest,
)
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "The caller has no role, or (for writes) is not a platform administrator (`forbidden`)",
    404: "No catalogue entry with this id, or no such version (`not_found`)",
    409: "An active entry of the same kind already has this code or name (`catalogue_duplicate`)",
    412: "The entry changed since the caller read it (`row_version_mismatch`)",
    422: "A field is blank or too long (the `detail` is the sentence to show), an unknown "
    "field, or an id that is not a UUID (`validation_error`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}
_ETAG_HEADER = {
    "ETag": {
        "description": "The entry's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the entry as last read (its `row_version`), e.g. `"3"`.',
    ),
]


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


def _with_etag(response: Response, entry: CatalogueEntry) -> CatalogueEntry:
    response.headers["ETag"] = etag(entry.row_version)
    return entry


router = APIRouter(prefix="/catalogue/entries", tags=["catalogue"])
_WRITE = _responses(403, 404, 409, 412, 422, 428)


@router.get("", operation_id="list_catalogue_entries", responses=_responses(403, 422))
async def list_catalogue_entries(
    actor: CurrentPrincipal,
    uow: UoW,
    kind: Annotated[Kind | None, Query(description="Only entries of this kind.")] = None,
    include_retired: Annotated[bool, Query(description="Include retired entries.")] = False,
) -> CatalogueList:
    """The catalogue at each entry's current version, by kind then name. Active entries
    only unless `include_retired`. Any user with a role."""
    return await knowledge.list_entries(uow, actor, kind=kind, include_retired=include_retired)


@router.post(
    "",
    operation_id="create_catalogue_entry",
    status_code=201,
    responses={
        **_responses(403, 409, 422),
        201: {"description": "The new entry, at version 1", "headers": _ETAG_HEADER},
    },
)
async def create_catalogue_entry(
    body: NewEntry, actor: CurrentPrincipal, uow: UoW, response: Response
) -> CatalogueEntry:
    """Create an Integration Type or Work Package. Platform administrators only."""
    return _with_etag(response, await knowledge.create_entry(uow, actor, body))


@router.get(
    "/{entry_id}",
    operation_id="get_catalogue_entry",
    responses={
        **_responses(403, 404, 422),
        200: {"description": "The entry", "headers": _ETAG_HEADER},
    },
)
async def get_catalogue_entry(
    entry_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    version: Annotated[
        int | None,
        Query(
            ge=1, le=2_147_483_647, description="An earlier version; the current one if omitted."
        ),
    ] = None,
) -> CatalogueEntry:
    """One entry, retired or not (a retired one has `retired` true). Any user with a role."""
    return _with_etag(response, await knowledge.read_entry(uow, actor, entry_id, version))


@router.get(
    "/{entry_id}/versions",
    operation_id="list_catalogue_entry_versions",
    responses=_responses(403, 404, 422),
)
async def list_catalogue_entry_versions(
    entry_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> CatalogueVersionList:
    """Every version of the entry, newest first, with who saved it. Any user with a role."""
    return await knowledge.read_versions(uow, actor, entry_id)


@router.patch(
    "/{entry_id}",
    operation_id="edit_catalogue_entry",
    responses={**_WRITE, 200: {"description": "The entry", "headers": _ETAG_HEADER}},
)
async def edit_catalogue_entry(
    entry_id: UUID,
    body: EntryChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> CatalogueEntry:
    """Change the name and/or definition. A changed value saves a new version; nothing
    changed writes nothing. Platform administrators only."""
    changed = await knowledge.edit_entry(uow, actor, entry_id, body, if_match)
    return _with_etag(response, changed)


@router.post(
    "/{entry_id}/retire",
    operation_id="retire_catalogue_entry",
    responses={**_WRITE, 200: {"description": "The entry", "headers": _ETAG_HEADER}},
)
async def retire_catalogue_entry(
    entry_id: UUID,
    body: RetireRequest,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> CatalogueEntry:
    """Retire an entry, with a reason. It can't be chosen for new tags, but references to
    it keep resolving. Platform administrators only."""
    retired = await knowledge.retire_entry(uow, actor, entry_id, body, if_match)
    return _with_etag(response, retired)


@router.post(
    "/{entry_id}/reactivate",
    operation_id="reactivate_catalogue_entry",
    responses={**_WRITE, 200: {"description": "The entry", "headers": _ETAG_HEADER}},
)
async def reactivate_catalogue_entry(
    entry_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> CatalogueEntry:
    """Reactivate a retired entry, unless an active entry of the same kind now has its code
    or name (409). Platform administrators only."""
    reactivated = await knowledge.reactivate_entry(uow, actor, entry_id, if_match)
    return _with_etag(response, reactivated)
