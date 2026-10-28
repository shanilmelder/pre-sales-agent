"""Actuals routes (Story 10.1), under `/api/v1/opportunities/{opportunity_id}`:

- `GET …/actuals`: the Actuals tab (anyone who can read the Opportunity), with its `ETag`;
- `POST …/actuals` with `If-Match` the tab's ETag: **Save Actuals** (records and corrections);
- `POST …/actuals/{actual_id}/corrections` with `If-Match` the Actual's version: correct it;
- `POST …/actuals/delivery/close` with `If-Match` the tab's ETag: **Close delivery**.

Story 10.2, importing Actuals from a file: `GET …/actuals/template`, `POST …/actuals/imports`
(multipart), `GET …/actuals/imports/latest` and `…/{import_id}`, `POST …/{import_id}/retry`
and `POST …/{import_id}/apply` with `If-Match` the tab's ETag.

Writes are for delivery managers only; everyone else who can read the Opportunity gets 403.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from app.modules.actuals.application import imports
from app.modules.actuals.application import public as actuals
from app.modules.actuals.application.public import (
    ActualCorrection,
    ActualsImportApply,
    ActualsImportLatest,
    ActualsImportView,
    ActualsSave,
    ActualsTemplate,
    ActualsView,
    AppliedImport,
    SavedActuals,
)
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.concurrency import etag
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.multipart import MultipartFile
from app.platform.storage import BlobStore
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): only delivery managers who can read the Opportunity "
    "record Actuals",
    404: "No Opportunity with this id, or the caller may not see it, or no Actual with this "
    "id in it (`not_found`)",
    409: "No Baseline yet (`actuals_no_baseline`) or delivery is closed (`delivery_closed`)",
    412: "Actuals changed since the caller read them (`row_version_mismatch`)",
    422: "`validation_error`: a malformed id or body; `actual_invalid`: an Actual breaks a "
    "rule, each listed in `errors` as `{item, field, message}`",
    428: "No `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}
_ETAG = {"ETag": {"description": "The Actuals tab's `row_version`", "schema": {"type": "string"}}}


def _responses(
    *codes: int, described: dict[int, str] | None = None
) -> dict[int | str, dict[str, Any]]:
    responses: dict[int | str, dict[str, Any]] = {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }
    for code, text in (described or {}).items():
        responses[code] = {"description": text, "content": PROBLEM_CONTENT}
    return responses


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["actuals"])

_TAB_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The Actuals tab ETag as last read (its `row_version`), e.g. `"4"`.',
    ),
]
_ACTUAL_IF_MATCH = Annotated[
    str | None,
    Header(alias="If-Match", description='The Actual `version` as last read, e.g. `"1"`.'),
]


@router.get(
    "/actuals",
    operation_id="get_actuals",
    responses={**_responses(404, 422), 200: {"description": "The tab", "headers": _ETAG}},
)
async def get_actuals(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW, request: Request, response: Response
) -> ActualsView:
    """The Actuals tab: every Baseline line with its estimate, current Actual and
    server-calculated variance, Unplanned work, totals, the Baseline version's Assumptions
    Register, and whether the caller may record Actuals or close delivery. Story 10.4: each
    failed Assumption with its number, hours, who accepted it and its Evidence. Anyone who can
    read the Opportunity."""
    settings: Settings = request.app.state.settings
    view = await actuals.get_actuals(
        uow, actor, opportunity_id, store=BlobStore(settings.storage_dir)
    )
    response.headers["ETag"] = etag(view.row_version)
    return view


@router.post(
    "/actuals",
    operation_id="save_actuals",
    responses={
        **_responses(403, 404, 409, 412, 422, 428),
        200: {"description": "What was saved, and the tab", "headers": _ETAG},
    },
)
async def save_actuals(
    opportunity_id: UUID,
    body: ActualsSave,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _TAB_IF_MATCH = None,
) -> SavedActuals:
    """**Save Actuals**: record each entry against its Baseline line (or as Unplanned work),
    correcting a line that already has an Actual (a new version; `reason` required), in one
    Unit of Work. Delivery managers only."""
    saved = await actuals.save_actuals(uow, actor, opportunity_id, body, if_match)
    response.headers["ETag"] = etag(saved.view.row_version)
    return saved


@router.post(
    "/actuals/{actual_id}/corrections",
    operation_id="correct_actual",
    status_code=201,
    responses={
        **_responses(403, 404, 409, 412, 422, 428),
        201: {"description": "The correction, and the tab", "headers": _ETAG},
    },
)
async def correct_actual(
    opportunity_id: UUID,
    actual_id: UUID,
    body: ActualCorrection,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _ACTUAL_IF_MATCH = None,
) -> SavedActuals:
    """Correct an Actual with a reason: a new version, tied to the Estimate Version the Actual
    was recorded against. Delivery managers only."""
    saved = await actuals.correct_actual(uow, actor, opportunity_id, actual_id, body, if_match)
    response.headers["ETag"] = etag(saved.view.row_version)
    return saved


@router.post(
    "/actuals/delivery/close",
    operation_id="close_delivery",
    responses={
        **_responses(
            403,
            404,
            412,
            422,
            428,
            described={
                409: "No Baseline yet (`actuals_no_baseline`), delivery already closed "
                "(`delivery_closed`), or lines without a final Actual (`delivery_not_ready`, "
                "with `open_line_count`)"
            },
        ),
        200: {"description": "The tab, delivery closed", "headers": _ETAG},
    },
)
async def close_delivery(
    opportunity_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _TAB_IF_MATCH = None,
) -> ActualsView:
    """**Close delivery** once every Baseline line has a final Actual: the Opportunity becomes
    `delivered`. Delivery managers only."""
    view = await actuals.close_delivery(uow, actor, opportunity_id, if_match)
    response.headers["ETag"] = etag(view.row_version)
    return view


# --- imports (Story 10.2) -------------------------------------------------------------------

_IMPORT_DESCRIBED: dict[int, str] = {
    403: "Not allowed (`forbidden`): only delivery managers who can read the Opportunity "
    "import Actuals",
    404: "No Opportunity with this id, or the caller may not see it, or no import with this "
    "id in it (`not_found`)",
    409: "No Baseline yet (`actuals_no_baseline`) or delivery is closed (`delivery_closed`)",
    413: "Rejected file: larger than the Actuals import limit (`file_too_large`; the `detail` "
    "is the sentence to show)",
    415: "Rejected file: not .xlsx or .csv (`file_type_not_allowed`), or its content does not "
    "match its extension (`file_content_mismatch`); the `detail` is the sentence to show",
    422: "`validation_error`: an empty file, no `file` part, an unusable file name, or an id "
    "that is not a UUID",
}
_RETRY_409 = "Only an import whose reading failed can be retried (`parse_not_failed`)"
_APPLY_409 = (
    "No Baseline yet (`actuals_no_baseline`), delivery closed (`delivery_closed`), the file "
    "not read yet or its reading failed (`actuals_import_not_ready`), already applied "
    "(`actuals_import_applied`), or the same file was already applied and `confirm_repeat` is "
    "false (`actuals_import_repeated`, with `applied_at`)"
)
_APPLY_422 = (
    "`validation_error`: a malformed id or body; `actual_invalid`: rows break a rule, each "
    "listed in `errors` as `{item, field, message}` (`item`: the sheet row; `message`, e.g. "
    '"Row 7: line ID not in Baseline v3")'
)


def _import_responses(
    *codes: int, described: dict[int, str] | None = None
) -> dict[int | str, dict[str, Any]]:
    texts = {code: _IMPORT_DESCRIBED[code] for code in codes if code in _IMPORT_DESCRIBED}
    texts.update(described or {})
    plain = [code for code in codes if code not in texts]
    return _responses(*plain, described=texts)


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
                            "description": "One .xlsx or .csv file of Actuals (start from the "
                            "template), at most `PSA_ACTUALS_IMPORT_MAX_BYTES` (5 MB).",
                        }
                    },
                }
            }
        },
    }
}


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None or not raw.strip().isascii() or not raw.strip().isdigit():
        return None
    return int(raw)


def _storage(request: Request) -> imports.ImportStorage:
    settings: Settings = request.app.state.settings
    return imports.ImportStorage(
        store=BlobStore(settings.storage_dir),
        signing_key=settings.download_signing_key,
        ttl_s=settings.download_link_ttl_s,
    )


@router.get(
    "/actuals/template",
    operation_id="get_actuals_template",
    responses={
        **_import_responses(403, 404, 409, 422),
        200: {"description": "A short-lived signed link to the template"},
    },
)
async def get_actuals_template(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW, request: Request
) -> ActualsTemplate:
    """**Download template**: the Baseline version's `.xlsx` with one row per line (Line ID,
    Line, Integration Type, Work Package, Estimate h) and empty Actual columns, as a
    short-lived signed link; traced with the Opportunity. Delivery managers only."""
    return await imports.download_template(uow, actor, opportunity_id, _storage(request))


@router.post(
    "/actuals/imports",
    operation_id="create_actuals_import",
    status_code=202,
    responses={
        **_import_responses(403, 404, 409, 413, 415, 422),
        202: {"description": "The import, `queued` for reading"},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def create_actuals_import(
    opportunity_id: UUID, request: Request, actor: CurrentPrincipal, uow: UoW
) -> ActualsImportView:
    """**Choose file**: upload one .xlsx or .csv of Actuals. It is checked and stored, and the
    worker reads it; poll `GET …/actuals/imports/{id}` for the preview. Nothing is written to
    the Actuals until **Confirm**. Delivery managers only."""
    settings: Settings = request.app.state.settings
    incoming = MultipartFile(
        request.stream(),
        request.headers.get("content-type"),
        field="file",
        max_body=imports.max_body_bytes(settings.actuals_import_max_bytes),
    )
    return await imports.upload_import(
        uow,
        actor,
        opportunity_id,
        incoming,
        store=BlobStore(settings.storage_dir),
        max_bytes=settings.actuals_import_max_bytes,
        content_length=_content_length(request),
    )


@router.get(
    "/actuals/imports/latest",
    operation_id="get_latest_actuals_import",
    responses={**_import_responses(403, 404, 422), 200: {"description": "The latest import"}},
)
async def get_latest_actuals_import(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> ActualsImportLatest:
    """The Opportunity's most recent import (null when none), with its preview once read.
    Delivery managers only."""
    return await imports.latest_import(uow, actor, opportunity_id)


@router.get(
    "/actuals/imports/{import_id}",
    operation_id="get_actuals_import",
    responses={**_import_responses(403, 404, 422), 200: {"description": "The import"}},
)
async def get_actuals_import(
    opportunity_id: UUID, import_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> ActualsImportView:
    """The import's status and, once read, its preview: each row checked now with the
    manual-entry rules (to create, to correct, invalid with its reasons, or skipped as
    blank), and whether the same file was already imported. Delivery managers only."""
    return await imports.get_import(uow, actor, opportunity_id, import_id)


@router.post(
    "/actuals/imports/{import_id}/retry",
    operation_id="retry_actuals_import",
    responses={
        **_import_responses(403, 404, 422, described={409: _RETRY_409}),
        200: {"description": "The import, `queued` again"},
    },
)
async def retry_actuals_import(
    opportunity_id: UUID, import_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> ActualsImportView:
    """**Retry** reading a file whose reading failed. Delivery managers only."""
    return await imports.retry_import(uow, actor, opportunity_id, import_id)


@router.post(
    "/actuals/imports/{import_id}/apply",
    operation_id="apply_actuals_import",
    responses={
        **_import_responses(403, 404, 412, 428, described={409: _APPLY_409, 422: _APPLY_422}),
        200: {"description": "The applied import, and the tab", "headers": _ETAG},
    },
)
async def apply_actuals_import(
    opportunity_id: UUID,
    import_id: UUID,
    body: ActualsImportApply,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _TAB_IF_MATCH = None,
) -> AppliedImport:
    """**Confirm** the preview: every row not excluded or blank is recorded or corrected in
    one Unit of Work with the rules of **Save Actuals**, or nothing is. `If-Match` is the
    Actuals tab ETag the preview showed. Delivery managers only."""
    applied = await imports.apply_import(uow, actor, opportunity_id, import_id, body, if_match)
    response.headers["ETag"] = etag(applied.actuals.row_version)
    return applied
