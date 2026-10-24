"""Opportunity Source routes (Story 2.1), under
`/api/v1/opportunities/{opportunity_id}/sources`, and Requirement routes (Story 2.5 Part A):
`…/{opportunity_id}/requirements` and `…/{opportunity_id}/extractions`, the cited-passage
route (Story 2.5 Part B): `…/{opportunity_id}/passages/{passage_id}`, and the Requirement
edit routes (Story 2.6): `PATCH …/requirements/{requirement_id}`,
`POST …/requirements/{requirement_id}/confirm` and `POST …/requirements/confirm-all`, and
the pending-change routes (Story 2.7): `POST …/requirements/{requirement_id}/change/accept`
and `…/change/reject`, the list-shaping routes (Story 2.6 remainder): `POST …/requirements`,
`POST …/requirements/merge`, `POST …/requirements/{requirement_id}/delete` and `…/split`,
the Integration Type tag route (Story 4.1): `PUT …/requirements/{requirement_id}/integration-types`,
and the Source viewer routes (Story 2.3):
`GET …/sources/{source_id}/versions/{version}/text` and `POST …/download-link`.

Uploads are `multipart/form-data` with the file in the `file` field. The body is read as a
stream (`app.platform.multipart`), never parsed up front, so a rejected type is answered
before its bytes are read and an oversized file as soon as it passes the limit. Pasted
text is JSON `{"text": ...}` at `…/sources/text`.
"""

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.intake.application import public as intake
from app.modules.intake.application.public import (
    AddTextSource,
    ConfirmAllResult,
    Extraction,
    OpportunitySourceDownloadLink,
    OpportunitySourceText,
    Passage,
    RemovedRequirement,
    Requirement,
    RequirementChangeRejection,
    RequirementChanges,
    RequirementDeletion,
    RequirementDraft,
    RequirementIntegrationTypes,
    RequirementList,
    RequirementMerge,
    RequirementSplit,
    Source,
    SourceList,
    SplitResult,
)
from app.platform.concurrency import etag
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, FileTooLargeError, Problem
from app.platform.multipart import MultipartFile
from app.platform.storage import BlobStore
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is neither "
    "its owner nor a collaborator",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    409: "The Source's latest version has not failed to parse (`parse_not_failed`)",
    422: "Rejected file: `file_too_large`, `file_type_not_allowed`, "
    "`file_content_mismatch`, `file_empty` (the `detail` is the sentence to show), or "
    "`validation_error` (no `file` part, or an unusable file name)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "One file: .eml, .msg, .txt, .vtt, .docx or .pdf, "
                            "at most `PSA_UPLOAD_MAX_BYTES` (50 MB).",
                        }
                    },
                }
            }
        },
    }
}

router = APIRouter(prefix="/opportunities/{opportunity_id}/sources", tags=["intake"])


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None or not raw.strip().isascii() or not raw.strip().isdigit():
        return None
    return int(raw)


@router.post(
    "",
    operation_id="add_source",
    status_code=201,
    responses={**_responses(403, 404, 422), 201: {"description": "The added Source"}},
    openapi_extra=_UPLOAD_BODY,
)
async def add_source(
    opportunity_id: UUID,
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
) -> Source:
    """Upload a file as a Source of the Opportunity. Its owner and collaborators only.
    The same bytes uploaded again become the next version of the Source holding them."""
    settings: Settings = request.app.state.settings
    incoming = MultipartFile(
        request.stream(),
        request.headers.get("content-type"),
        field="file",
        max_body=intake.max_body_bytes(settings.upload_max_bytes),
    )
    source = await intake.add_file(
        uow,
        actor,
        opportunity_id,
        incoming,
        store=BlobStore(settings.storage_dir),
        max_bytes=settings.upload_max_bytes,
        content_length=_content_length(request),
    )
    return source


_TEXT_RESPONSES = _responses(403, 404, 422)
_TEXT_RESPONSES[422] = {
    "description": "Rejected text: `file_empty` (blank once trimmed), `file_too_large` "
    "(longer than 1,000,000 characters once trimmed), `file_content_mismatch` (a NUL "
    "character or a lone surrogate); the `detail` is the sentence to show. Or "
    "`validation_error` (no `text` string, or an unknown field)",
    "content": PROBLEM_CONTENT,
}
_TEXT_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": AddTextSource.model_json_schema()}},
    }
}


async def _text_body(request: Request) -> AddTextSource:
    """The JSON body read as a stream and capped at `TEXT_BODY_MAX_BYTES`, so an oversized
    body is refused before it is buffered. Parsed with `json.loads`, which keeps a lone
    surrogate escape for the command to reject as unsupported characters."""
    content_length = _content_length(request)
    if content_length is not None and content_length > intake.TEXT_BODY_MAX_BYTES:
        raise FileTooLargeError(intake.TEXT_TOO_LONG_MESSAGE)
    body = bytearray()
    try:
        async for chunk in request.stream():
            body += chunk
            if len(body) > intake.TEXT_BODY_MAX_BYTES:
                raise FileTooLargeError(intake.TEXT_TOO_LONG_MESSAGE)
    except ClientDisconnect:
        raise RequestValidationError([_invalid_json()]) from None
    try:
        data = json.loads(body)
    except ValueError:
        raise RequestValidationError([_invalid_json()]) from None
    try:
        return AddTextSource.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**err, "loc": ("body", *err["loc"])} for err in exc.errors()]
        ) from None


def _invalid_json() -> dict[str, Any]:
    return {"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON", "input": None}


@router.post(
    "/text",
    operation_id="add_text_source",
    status_code=201,
    responses={**_TEXT_RESPONSES, 201: {"description": "The added Source"}},
    openapi_extra=_TEXT_BODY,
)
async def add_text_source(
    opportunity_id: UUID,
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
) -> Source:
    """Add pasted text as a `note` Source named `Pasted text`. Its owner and collaborators
    only. The trimmed text is stored like a `.txt` upload, so the same bytes again become
    the next version of the Source holding them."""
    body = await _text_body(request)
    settings: Settings = request.app.state.settings
    return await intake.add_text(
        uow, actor, opportunity_id, body.text, store=BlobStore(settings.storage_dir)
    )


_LIST_RESPONSES = _responses(404)
_LIST_RESPONSES[422] = {
    "description": "The Opportunity id is not a UUID (`validation_error`)",
    "content": PROBLEM_CONTENT,
}


@router.get("", operation_id="list_sources", responses=_LIST_RESPONSES)
async def list_sources(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> SourceList:
    """The Opportunity's Sources, newest first, each with its latest version. Anyone who
    can read the Opportunity."""
    return await intake.list_sources(uow, actor, opportunity_id)


_RETRY_RESPONSES = _responses(403, 404, 409)
_RETRY_RESPONSES[404] = {
    "description": "No Opportunity with this id, or the caller may not see it, or no Source "
    "with this id in it (`not_found`)",
    "content": PROBLEM_CONTENT,
}
_RETRY_RESPONSES[422] = {
    "description": "An id is not a UUID (`validation_error`)",
    "content": PROBLEM_CONTENT,
}


@router.post(
    "/{source_id}/parse",
    operation_id="retry_source_parse",
    status_code=202,
    responses={**_RETRY_RESPONSES, 202: {"description": "The Source, its parse `queued`"}},
)
async def retry_source_parse(
    opportunity_id: UUID, source_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> Source:
    """Parse the Source's latest version again after it failed: sets it back to `queued` and
    enqueues a new parse job. The Opportunity's owner and collaborators only."""
    return await intake.retry_parse(uow, actor, opportunity_id, source_id)


# --- the Source viewer (Story 2.3) ----------------------------------------------------------

_VIEWER_RESPONSES = _responses(404)
_VIEWER_RESPONSES[404] = {
    "description": "No Opportunity with this id, or the caller may not see it, or no such "
    "Source version in it (`not_found`)",
    "content": PROBLEM_CONTENT,
}
_VIEWER_RESPONSES[422] = {
    "description": "An id is not a UUID, or the version is not a positive integer "
    "(`validation_error`)",
    "content": PROBLEM_CONTENT,
}
_TEXT_RESPONSES = {
    **_VIEWER_RESPONSES,
    404: {
        "description": "No Opportunity with this id, or the caller may not see it, or no such "
        "Source version in it, or the version is not parsed (`not_found`)",
        "content": PROBLEM_CONTENT,
    },
}
SourceVersion = Annotated[int, Path(ge=1, le=2_147_483_647)]


@router.get(
    "/{source_id}/versions/{version}/text",
    operation_id="get_source_text",
    responses=_TEXT_RESPONSES,
)
async def get_source_text(
    opportunity_id: UUID,
    source_id: UUID,
    version: SourceVersion,
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
) -> OpportunitySourceText:
    """The extracted text of a parsed Source version, exactly as stored. 404 until it is
    parsed. Anyone who can read the Opportunity."""
    settings: Settings = request.app.state.settings
    return await intake.source_text(
        uow, actor, opportunity_id, source_id, version, store=BlobStore(settings.storage_dir)
    )


@router.post(
    "/{source_id}/versions/{version}/download-link",
    operation_id="create_source_download_link",
    responses=_VIEWER_RESPONSES,
)
async def create_source_download_link(
    opportunity_id: UUID,
    source_id: UUID,
    version: SourceVersion,
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
) -> OpportunitySourceDownloadLink:
    """A short-lived signed link to a Source version's original file, served unchanged as
    an attachment under its stored file name. Anyone who can read the Opportunity."""
    settings: Settings = request.app.state.settings
    return await intake.source_download_link(
        uow,
        actor,
        opportunity_id,
        source_id,
        version,
        signing_key=settings.download_signing_key,
        ttl_s=settings.download_link_ttl_s,
    )


# --- Requirements (Story 2.5 Part A) --------------------------------------------------------

requirements_router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["intake"])


@requirements_router.get(
    "/requirements", operation_id="list_requirements", responses=_LIST_RESPONSES
)
async def list_requirements(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> RequirementList:
    """The Opportunity's active Requirements, oldest first, each with the Source passages it
    cites, and its latest extraction (null before the first). Anyone who can read the
    Opportunity."""
    return await intake.list_requirements(uow, actor, opportunity_id)


_START_RESPONSES = _responses(403, 404)
_START_RESPONSES[409] = {
    "description": "An extraction is already queued or running (`extraction_in_progress`), "
    "or the Intake Agent is disabled in the Agent Registry (`registry_agent_disabled`)",
    "content": PROBLEM_CONTENT,
}
_START_RESPONSES[422] = _LIST_RESPONSES[422]


@requirements_router.post(
    "/extractions",
    operation_id="start_extraction",
    status_code=201,
    responses={**_START_RESPONSES, 201: {"description": "The new extraction, `queued`"}},
)
async def start_extraction(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> Extraction:
    """Queue a new Requirement extraction over the Opportunity's parsed Sources, e.g. to
    retry a failed one. The Opportunity's owner and collaborators only."""
    return await intake.start_extraction(uow, actor, opportunity_id)


_PASSAGE_RESPONSES = _responses(404)
_PASSAGE_RESPONSES[404] = {
    "description": "No Opportunity with this id, or the caller may not see it, or no passage "
    "with this id in it (`not_found`)",
    "content": PROBLEM_CONTENT,
}
_PASSAGE_RESPONSES[422] = {
    "description": "An id is not a UUID (`validation_error`)",
    "content": PROBLEM_CONTENT,
}


@requirements_router.get(
    "/passages/{passage_id}", operation_id="get_passage", responses=_PASSAGE_RESPONSES
)
async def get_passage(
    opportunity_id: UUID, passage_id: UUID, request: Request, actor: CurrentPrincipal, uow: UoW
) -> Passage:
    """A cited Source passage in its surrounding text: `text` is the span exactly, `before`
    and `after` up to 300 code points of context each, cut at whitespace, with `…` on a side
    that was cut. Anyone who can read the Opportunity."""
    settings: Settings = request.app.state.settings
    return await intake.get_passage(
        uow, actor, opportunity_id, passage_id, store=BlobStore(settings.storage_dir)
    )


# --- Requirement edits (Story 2.6) ----------------------------------------------------------

_EDIT_DESCRIBED: dict[int, str] = {
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, or is a sales representative",
    404: "No Opportunity with this id, or the caller may not see it, or no active Requirement "
    "with this id in it (`not_found`)",
    409: "The Requirement has no pending change (`no_pending_change`)",
    412: "The Requirement changed since the caller read it (`row_version_mismatch`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
}
_ETAG_HEADER = {
    "ETag": {
        "description": "The Requirement's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Requirement as last read (its `row_version`), e.g. `"3"`.',
    ),
]


def _edit_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    responses = _responses()
    for code in codes:
        responses[code] = {"description": _EDIT_DESCRIBED[code], "content": PROBLEM_CONTENT}
    return responses


def _with_etag(response: Response, requirement: Requirement) -> Requirement:
    response.headers["ETag"] = etag(requirement.row_version)
    return requirement


_PATCH_RESPONSES = _edit_responses(403, 404, 412, 428)
_PATCH_RESPONSES[422] = {
    "description": "`validation_error`: the text is blank or longer than 2,000 characters "
    "once trimmed (the `detail` is the sentence to show), an unknown classification or "
    "field, or an id that is not a UUID",
    "content": PROBLEM_CONTENT,
}


@requirements_router.patch(
    "/requirements/{requirement_id}",
    operation_id="edit_requirement",
    responses={
        **_PATCH_RESPONSES,
        200: {"description": "The Requirement", "headers": _ETAG_HEADER},
    },
)
async def edit_requirement(
    opportunity_id: UUID,
    requirement_id: UUID,
    body: RequirementChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Requirement:
    """Change a Requirement's text and/or classification. A change makes its next version,
    marks it `human` and locks it against re-extraction; its Evidence stays. Nothing
    changed: nothing is written. The owner and collaborators, except sales
    representatives."""
    changed = await intake.edit_requirement(
        uow, actor, opportunity_id, requirement_id, body, if_match
    )
    return _with_etag(response, changed)


_CONFIRM_RESPONSES = _edit_responses(403, 404, 412, 428)
_CONFIRM_RESPONSES[422] = {
    "description": "An id is not a UUID (`validation_error`)",
    "content": PROBLEM_CONTENT,
}


@requirements_router.post(
    "/requirements/confirm-all",
    operation_id="confirm_all_requirements",
    responses={
        **_edit_responses(403, 404),
        422: _LIST_RESPONSES[422],
        200: {"description": "How many Requirements were confirmed"},
    },
)
async def confirm_all_requirements(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> ConfirmAllResult:
    """Confirm every active Requirement not confirmed yet, locking them against
    re-extraction. No `If-Match`: only unconfirmed Requirements change. The owner and
    collaborators, except sales representatives."""
    return await intake.confirm_all(uow, actor, opportunity_id)


@requirements_router.post(
    "/requirements/{requirement_id}/confirm",
    operation_id="confirm_requirement",
    responses={
        **_CONFIRM_RESPONSES,
        200: {"description": "The Requirement", "headers": _ETAG_HEADER},
    },
)
async def confirm_requirement(
    opportunity_id: UUID,
    requirement_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Requirement:
    """Confirm a Requirement, locking it against re-extraction; its version stays. Already
    confirmed: nothing changes. The owner and collaborators, except sales
    representatives."""
    confirmed = await intake.confirm_requirement(
        uow, actor, opportunity_id, requirement_id, if_match
    )
    return _with_etag(response, confirmed)


# --- pending changes (Story 2.7) ------------------------------------------------------------

_CHANGE_RESPONSES = _edit_responses(403, 404, 409, 412, 428)
_CHANGE_RESPONSES[422] = _CONFIRM_RESPONSES[422]
_REJECT_RESPONSES = _edit_responses(403, 404, 409, 412, 428)
_REJECT_RESPONSES[422] = {
    "description": "`validation_error`: the reason is blank or longer than 500 characters "
    "once trimmed (the `detail` is the sentence to show), an unknown field, or an id that is "
    "not a UUID",
    "content": PROBLEM_CONTENT,
}


@requirements_router.post(
    "/requirements/{requirement_id}/change/accept",
    operation_id="accept_requirement_change",
    responses={
        **_CHANGE_RESPONSES,
        200: {"description": "The Requirement at its new version", "headers": _ETAG_HEADER},
    },
)
async def accept_requirement_change(
    opportunity_id: UUID,
    requirement_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Requirement:
    """Accept the Requirement's pending change: its proposed text and classification become
    the next version, its new Evidence is cited, and the Requirement stays locked as
    `human`. The owner and collaborators, except sales representatives."""
    accepted = await intake.accept_requirement_change(
        uow, actor, opportunity_id, requirement_id, if_match
    )
    return _with_etag(response, accepted)


@requirements_router.post(
    "/requirements/{requirement_id}/change/reject",
    operation_id="reject_requirement_change",
    responses={
        **_REJECT_RESPONSES,
        200: {"description": "The Requirement, unchanged", "headers": _ETAG_HEADER},
    },
)
async def reject_requirement_change(
    opportunity_id: UUID,
    requirement_id: UUID,
    body: RequirementChangeRejection,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Requirement:
    """Reject the Requirement's pending change with a reason; the Requirement keeps its
    text, classification and version. The owner and collaborators, except sales
    representatives."""
    rejected = await intake.reject_requirement_change(
        uow, actor, opportunity_id, requirement_id, body, if_match
    )
    return _with_etag(response, rejected)


# --- Integration Type tags (Story 4.1) ------------------------------------------------------

_TAG_RESPONSES = _edit_responses(403, 404, 412, 428)
_TAG_RESPONSES[422] = {
    "description": "`validation_error`: a newly added id is not an active catalogue "
    "Integration Type (the `detail` is the sentence to show), more than 50 ids, an unknown "
    "field, or an id that is not a UUID",
    "content": PROBLEM_CONTENT,
}


@requirements_router.put(
    "/requirements/{requirement_id}/integration-types",
    operation_id="tag_requirement_integration_types",
    responses={
        **_TAG_RESPONSES,
        200: {"description": "The Requirement", "headers": _ETAG_HEADER},
    },
)
async def tag_requirement_integration_types(
    opportunity_id: UUID,
    requirement_id: UUID,
    body: RequirementIntegrationTypes,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Requirement:
    """Replace a Requirement's Integration Type tags. Its version stays; its `row_version`
    moves on. An unchanged set writes nothing. The owner and collaborators, except sales
    representatives."""
    tagged = await intake.tag_requirement_integration_types(
        uow, actor, opportunity_id, requirement_id, body, if_match
    )
    return _with_etag(response, tagged)


# --- shaping the list (Story 2.6 remainder) -------------------------------------------------

_TEXT_422 = (
    "`validation_error`: a text is blank or longer than 2,000 characters once trimmed (the "
    "`detail` is the sentence to show), an unknown classification or field"
)
_CREATE_RESPONSES = _edit_responses(403, 404)
_CREATE_RESPONSES[422] = {"description": f"{_TEXT_422}.", "content": PROBLEM_CONTENT}


@requirements_router.post(
    "/requirements",
    operation_id="create_requirement",
    status_code=201,
    responses={
        **_CREATE_RESPONSES,
        201: {"description": "The new Requirement", "headers": _ETAG_HEADER},
    },
)
async def create_requirement(
    opportunity_id: UUID,
    body: RequirementDraft,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
) -> Requirement:
    """Add a Requirement the extraction missed: origin `human`, locked, no Evidence,
    unconfirmed, with the Opportunity's next number. The owner and collaborators, except
    sales representatives."""
    created = await intake.create_requirement(uow, actor, opportunity_id, body)
    return _with_etag(response, created)


_MERGE_RESPONSES = _edit_responses(403, 404, 412)
_MERGE_RESPONSES[422] = {
    "description": f"{_TEXT_422}, fewer than 2 or more than 20 Requirements, the same "
    "Requirement twice, or an id that is not a UUID.",
    "content": PROBLEM_CONTENT,
}
_MERGE_RESPONSES[412] = {
    "description": "A Requirement changed since the caller read it (`row_version_mismatch`): "
    "nothing is merged",
    "content": PROBLEM_CONTENT,
}


@requirements_router.post(
    "/requirements/merge",
    operation_id="merge_requirements",
    status_code=201,
    responses={
        **_MERGE_RESPONSES,
        201: {"description": "The merged Requirement", "headers": _ETAG_HEADER},
    },
)
async def merge_requirements(
    opportunity_id: UUID,
    body: RequirementMerge,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
) -> Requirement:
    """Merge 2 to 20 active Requirements into one new Requirement citing all their Evidence;
    the originals are superseded. No `If-Match` header: each Requirement names the
    `row_version` the caller read, and any stale one fails the whole merge. The owner and
    collaborators, except sales representatives."""
    merged = await intake.merge_requirements(uow, actor, opportunity_id, body)
    return _with_etag(response, merged)


_DELETE_RESPONSES = _edit_responses(403, 404, 412, 428)
_DELETE_RESPONSES[422] = _REJECT_RESPONSES[422]


@requirements_router.post(
    "/requirements/{requirement_id}/delete",
    operation_id="delete_requirement",
    responses={**_DELETE_RESPONSES, 200: {"description": "The deleted Requirement"}},
)
async def delete_requirement(
    opportunity_id: UUID,
    requirement_id: UUID,
    body: RequirementDeletion,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _IF_MATCH = None,
) -> RemovedRequirement:
    """Delete a Requirement with a reason: it leaves the active list but stays in history,
    and re-extraction never brings it back. The owner and collaborators, except sales
    representatives."""
    return await intake.delete_requirement(
        uow, actor, opportunity_id, requirement_id, body, if_match
    )


_SPLIT_RESPONSES = _edit_responses(403, 404, 412, 428)
_SPLIT_RESPONSES[422] = {
    "description": f"{_TEXT_422}, not exactly two parts, or an id that is not a UUID.",
    "content": PROBLEM_CONTENT,
}


@requirements_router.post(
    "/requirements/{requirement_id}/split",
    operation_id="split_requirement",
    status_code=201,
    responses={**_SPLIT_RESPONSES, 201: {"description": "The two new Requirements"}},
)
async def split_requirement(
    opportunity_id: UUID,
    requirement_id: UUID,
    body: RequirementSplit,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _IF_MATCH = None,
) -> SplitResult:
    """Split a Requirement into two new Requirements, each citing all its Evidence; the
    original is superseded. The owner and collaborators, except sales representatives."""
    return await intake.split_requirement(
        uow, actor, opportunity_id, requirement_id, body, if_match
    )
