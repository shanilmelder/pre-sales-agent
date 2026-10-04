"""Opportunity Source routes (Story 2.1), under
`/api/v1/opportunities/{opportunity_id}/sources`, and Requirement routes (Story 2.5 Part A):
`…/{opportunity_id}/requirements` and `…/{opportunity_id}/extractions`.

Uploads are `multipart/form-data` with the file in the `file` field. The body is read as a
stream (`app.platform.multipart`), never parsed up front, so a rejected type is answered
before its bytes are read and an oversized file as soon as it passes the limit. Pasted
text is JSON `{"text": ...}` at `…/sources/text`.
"""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.intake.application import public as intake
from app.modules.intake.application.public import (
    AddTextSource,
    Extraction,
    RequirementList,
    Source,
    SourceList,
)
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
    "description": "An extraction is already queued or running (`extraction_in_progress`)",
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
