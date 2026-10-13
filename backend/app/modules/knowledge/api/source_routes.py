"""Knowledge Source routes (Story 3.2) under `/api/v1/knowledge/sources`. Reads: any user
with a role. Writes: platform administrators or the Source's owner; each takes the Source's
`ETag` back in `If-Match` (except registering and retrying a parse).

Uploads are `multipart/form-data` with the file in the `file` field, read as a stream
(`app.platform.multipart`) so a rejected type is answered before its bytes are read and an
oversized file as soon as it passes the limit. The other fields travel in the query string.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response

from app.modules.identity.application.public import CurrentPrincipal, UserSearchResult
from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import (
    DownloadLink,
    KnowledgeSource,
    KnowledgeSourceList,
    KnowledgeSourceVersionList,
    RetireSource,
    SourceChanges,
    SourceText,
)
from app.platform.concurrency import etag
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.multipart import MultipartFile
from app.platform.storage import BlobStore
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "The caller has no role, or (for writes) is neither a platform administrator nor "
    "the Source's owner (`forbidden`)",
    404: "No Knowledge Source with this id, or no such version (`not_found`)",
    409: "The Source is retired (`knowledge_source_retired`), or its latest version has not "
    "failed to parse (`parse_not_failed`)",
    412: "The Source changed since the caller read it (`row_version_mismatch`)",
    422: "Rejected file (`file_too_large`, `file_type_not_allowed`, `file_content_mismatch`, "
    "`file_empty`; the `detail` is the sentence to show), a field that is blank or too long, "
    "no active Integration Type tag, a retired tag or an owner with no role, or an id that is "
    "not a UUID (`validation_error`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}
_ETAG_HEADER = {
    "ETag": {
        "description": "The Source's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Source as last read (its `row_version`), e.g. `"3"`.',
    ),
]
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
                            "description": "One file: .pdf, .docx, .txt or .md, at most "
                            "`PSA_UPLOAD_MAX_BYTES` (50 MB).",
                        }
                    },
                }
            }
        },
    }
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


def _with_etag(response: Response, source: KnowledgeSource) -> KnowledgeSource:
    response.headers["ETag"] = etag(source.row_version)
    return source


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None or not raw.strip().isascii() or not raw.strip().isdigit():
        return None
    return int(raw)


def _incoming(request: Request, settings: Settings) -> MultipartFile:
    return MultipartFile(
        request.stream(),
        request.headers.get("content-type"),
        field="file",
        max_body=knowledge.max_body_bytes(settings.upload_max_bytes),
    )


router = APIRouter(prefix="/knowledge/sources", tags=["knowledge"])
_WRITE = _responses(403, 404, 409, 412, 422, 428)
_OK_ETAG: dict[int | str, dict[str, Any]] = {
    200: {"description": "The Source", "headers": _ETAG_HEADER}
}


@router.get("", operation_id="list_knowledge_sources", responses=_responses(403, 422))
async def list_knowledge_sources(
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
    product: Annotated[
        str | None, Query(max_length=200, description="Only this product (ignoring case).")
    ] = None,
    integration_type_id: Annotated[
        UUID | None, Query(description="Only Sources tagged with this Integration Type.")
    ] = None,
    owner_id: Annotated[UUID | None, Query(description="Only this owner's Sources.")] = None,
    stale: Annotated[
        bool | None, Query(description="True: only stale Sources. False: only fresh ones.")
    ] = None,
    include_retired: Annotated[bool, Query(description="Include retired Sources.")] = False,
) -> KnowledgeSourceList:
    """Sources at their latest version, longest-unreviewed first. Active ones only unless
    `include_retired`. Any user with a role."""
    settings: Settings = request.app.state.settings
    return await knowledge.list_sources(
        uow,
        actor,
        product=product,
        integration_type_id=integration_type_id,
        owner_id=owner_id,
        stale=stale,
        include_retired=include_retired,
        stale_months=settings.knowledge_stale_months,
    )


@router.post(
    "",
    operation_id="register_knowledge_source",
    status_code=201,
    responses={
        **_responses(403, 422),
        201: {"description": "The new Source, at version 1", "headers": _ETAG_HEADER},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def register_knowledge_source(
    request: Request,
    response: Response,
    actor: CurrentPrincipal,
    uow: UoW,
    title: Annotated[str, Query(max_length=1000, description="1-200 characters, trimmed.")],
    product: Annotated[str, Query(max_length=1000, description="1-120 characters, trimmed.")],
    product_version: Annotated[
        str, Query(max_length=1000, description="The product version it documents, 1-60.")
    ],
    integration_type_ids: Annotated[
        list[str],
        Query(description="Active Integration Type ids to tag with: at least one."),
    ],
    owner_id: Annotated[
        UUID | None,
        Query(
            description="The owner; the caller if omitted. Only administrators may name another."
        ),
    ] = None,
) -> KnowledgeSource:
    """Register a Knowledge Source by uploading its first file. Platform administrators only;
    the registrant owns it unless they name another user."""
    settings: Settings = request.app.state.settings
    source = await knowledge.register_source(
        uow,
        actor,
        _incoming(request, settings),
        title=title,
        product=product,
        product_version=product_version,
        integration_type_ids=integration_type_ids,
        owner_id=owner_id,
        store=BlobStore(settings.storage_dir),
        max_bytes=settings.upload_max_bytes,
        content_length=_content_length(request),
        stale_months=settings.knowledge_stale_months,
    )
    return _with_etag(response, source)


@router.get(
    "/owner-candidates",
    operation_id="search_knowledge_owners",
    responses=_responses(403, 422),
)
async def search_knowledge_owners(
    actor: CurrentPrincipal,
    uow: UoW,
    q: Annotated[str, Query(max_length=200, description="Part of a name or email.")],
) -> UserSearchResult:
    """Users an administrator may name as a Source's owner. Platform administrators only."""
    return await knowledge.search_owners(uow, actor, q)


@router.get(
    "/{source_id}",
    operation_id="get_knowledge_source",
    responses={**_responses(403, 404, 422), **_OK_ETAG},
)
async def get_knowledge_source(
    source_id: UUID, request: Request, response: Response, actor: CurrentPrincipal, uow: UoW
) -> KnowledgeSource:
    """One Source at its latest version, retired or not. Any user with a role."""
    settings: Settings = request.app.state.settings
    source = await knowledge.read_source(
        uow, actor, source_id, stale_months=settings.knowledge_stale_months
    )
    return _with_etag(response, source)


@router.patch(
    "/{source_id}",
    operation_id="edit_knowledge_source",
    responses={**_WRITE, **_OK_ETAG},
)
async def edit_knowledge_source(
    source_id: UUID,
    body: SourceChanges,
    request: Request,
    response: Response,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _IF_MATCH = None,
) -> KnowledgeSource:
    """Change the title, product, tags (retag) and, for administrators, the owner. A
    change that alters nothing writes nothing."""
    settings: Settings = request.app.state.settings
    source = await knowledge.edit_source(
        uow, actor, source_id, body, if_match, stale_months=settings.knowledge_stale_months
    )
    return _with_etag(response, source)


@router.get(
    "/{source_id}/versions",
    operation_id="list_knowledge_source_versions",
    responses=_responses(403, 404, 422),
)
async def list_knowledge_source_versions(
    source_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> KnowledgeSourceVersionList:
    """Every version of the Source, newest first, with its parse state. Any user with a
    role."""
    return await knowledge.read_source_versions(uow, actor, source_id)


@router.post(
    "/{source_id}/versions",
    operation_id="add_knowledge_source_version",
    status_code=201,
    responses={
        **_WRITE,
        201: {"description": "The Source at its new version", "headers": _ETAG_HEADER},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def add_knowledge_source_version(
    source_id: UUID,
    request: Request,
    response: Response,
    actor: CurrentPrincipal,
    uow: UoW,
    product_version: Annotated[
        str, Query(max_length=1000, description="The product version it documents, 1-60.")
    ],
    if_match: _IF_MATCH = None,
) -> KnowledgeSource:
    """Upload the next version of the Source. Earlier versions stay readable."""
    settings: Settings = request.app.state.settings
    source = await knowledge.add_version(
        uow,
        actor,
        source_id,
        _incoming(request, settings),
        product_version=product_version,
        if_match=if_match,
        store=BlobStore(settings.storage_dir),
        max_bytes=settings.upload_max_bytes,
        content_length=_content_length(request),
        stale_months=settings.knowledge_stale_months,
    )
    return _with_etag(response, source)


@router.get(
    "/{source_id}/versions/{version}/text",
    operation_id="get_knowledge_source_text",
    responses=_responses(403, 404, 422),
)
async def get_knowledge_source_text(
    source_id: UUID,
    version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
) -> SourceText:
    """The extracted text of a parsed version, as stored. 404 until it is parsed."""
    settings: Settings = request.app.state.settings
    return await knowledge.read_text(
        uow, actor, source_id, version, store=BlobStore(settings.storage_dir)
    )


@router.post(
    "/{source_id}/versions/{version}/download-link",
    operation_id="create_knowledge_source_download_link",
    responses=_responses(403, 404, 422),
)
async def create_knowledge_source_download_link(
    source_id: UUID,
    version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    request: Request,
    actor: CurrentPrincipal,
    uow: UoW,
) -> DownloadLink:
    """A short-lived signed link to the original file of a version (the current one or an
    earlier one), served unchanged. Any user with a role."""
    settings: Settings = request.app.state.settings
    return await knowledge.download_link(
        uow,
        actor,
        source_id,
        version,
        signing_key=settings.download_signing_key,
        ttl_s=settings.download_link_ttl_s,
    )


@router.post(
    "/{source_id}/review",
    operation_id="mark_knowledge_source_reviewed",
    responses={**_WRITE, **_OK_ETAG},
)
async def mark_knowledge_source_reviewed(
    source_id: UUID,
    request: Request,
    response: Response,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _IF_MATCH = None,
) -> KnowledgeSource:
    """Set the Source's last-reviewed date to today, clearing its stale flag."""
    settings: Settings = request.app.state.settings
    source = await knowledge.mark_reviewed(
        uow, actor, source_id, if_match, stale_months=settings.knowledge_stale_months
    )
    return _with_etag(response, source)


@router.post(
    "/{source_id}/retire",
    operation_id="retire_knowledge_source",
    responses={**_WRITE, **_OK_ETAG},
)
async def retire_knowledge_source(
    source_id: UUID,
    body: RetireSource,
    request: Request,
    response: Response,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _IF_MATCH = None,
) -> KnowledgeSource:
    """Retire the Source, with a reason. Its versions stay readable."""
    settings: Settings = request.app.state.settings
    source = await knowledge.retire_source(
        uow, actor, source_id, body, if_match, stale_months=settings.knowledge_stale_months
    )
    return _with_etag(response, source)


@router.post(
    "/{source_id}/parse",
    operation_id="retry_knowledge_source_parse",
    status_code=202,
    responses={
        **_responses(403, 404, 409, 422),
        202: {"description": "The Source, its parse `queued`", "headers": _ETAG_HEADER},
    },
)
async def retry_knowledge_source_parse(
    source_id: UUID, request: Request, response: Response, actor: CurrentPrincipal, uow: UoW
) -> KnowledgeSource:
    """Parse the Source's latest version again after it failed. Platform administrators or
    the Source's owner."""
    settings: Settings = request.app.state.settings
    source = await knowledge.retry_parse(
        uow, actor, source_id, stale_months=settings.knowledge_stale_months
    )
    return _with_etag(response, source)
