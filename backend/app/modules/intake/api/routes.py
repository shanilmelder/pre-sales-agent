"""Opportunity Source routes (Story 2.1 Part A), under
`/api/v1/opportunities/{opportunity_id}/sources`.

Uploads are `multipart/form-data` with the file in the `file` field. The body is read as a
stream (`app.platform.multipart`), never parsed up front, so a rejected type is answered
before its bytes are read and an oversized file as soon as it passes the limit.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.intake.application import public as intake
from app.modules.intake.application.public import Source, SourceList
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.multipart import MultipartFile
from app.platform.storage import BlobStore
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is neither "
    "its owner nor a collaborator",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
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
