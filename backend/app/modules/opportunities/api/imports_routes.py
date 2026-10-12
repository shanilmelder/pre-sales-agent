"""Opportunity import routes (Story 1.7, import from file), under
`/api/v1/opportunity-imports`.

Uploads are `multipart/form-data` with the file in the `file` field, read as a stream
(`app.platform.multipart`) with the same limits as a Source upload. The api process only
stores the file and queues `opportunities.read_import`; the worker reads it.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import imports
from app.modules.opportunities.application.public import OpportunityImport
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.multipart import MultipartFile
from app.platform.storage import BlobStore
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): only presales engineers create Opportunities",
    404: "No import with this id of the caller's (`not_found`)",
    410: "The import is older than 24 hours (`import_expired`)",
    413: "Rejected file: larger than the upload limit (`file_too_large`; the `detail` is the "
    "sentence to show)",
    415: "Rejected file: a type not allowed (`file_type_not_allowed`; the `detail` is the "
    "sentence to show)",
    422: "Rejected file: `file_content_mismatch`, `file_empty` (the `detail` is the sentence "
    "to show), or `validation_error` (no `file` part, an unusable file name, or an id that "
    "is not a UUID)",
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
                            "description": "One file: .eml, .vtt, .txt, .docx or .pdf (any "
                            "Source type), at most `PSA_UPLOAD_MAX_BYTES` (50 MB).",
                        }
                    },
                }
            }
        },
    }
}

router = APIRouter(prefix="/opportunity-imports", tags=["opportunities"])


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None or not raw.strip().isascii() or not raw.strip().isdigit():
        return None
    return int(raw)


@router.post(
    "",
    operation_id="create_opportunity_import",
    status_code=202,
    responses={
        **_responses(403, 413, 415, 422),
        202: {"description": "The import, `queued` for reading"},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def create_opportunity_import(
    request: Request, actor: CurrentPrincipal, uow: UoW
) -> OpportunityImport:
    """Upload one file to start a New Opportunity from. The worker reads it and suggests the
    form's fields; poll `GET /opportunity-imports/{id}`. Presales engineers only."""
    settings: Settings = request.app.state.settings
    incoming = MultipartFile(
        request.stream(),
        request.headers.get("content-type"),
        field="file",
        max_body=intake.max_body_bytes(settings.upload_max_bytes),
    )
    return await imports.upload_import(
        uow,
        actor,
        incoming,
        store=BlobStore(settings.storage_dir),
        max_bytes=settings.upload_max_bytes,
        content_length=_content_length(request),
    )


@router.get(
    "/{import_id}",
    operation_id="get_opportunity_import",
    responses=_responses(404, 410, 422),
)
async def get_opportunity_import(
    import_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> OpportunityImport:
    """The import's status (`queued`, `running`, `succeeded`, `failed`) and, once
    `succeeded`, its suggestions, each with the quote it came from. Its uploader only."""
    return await imports.get_import(uow, actor, import_id)
