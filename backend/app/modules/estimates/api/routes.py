"""Estimate routes (Stories 8.1 and 8.4): `GET /api/v1/opportunities/{opportunity_id}/estimate`,
`POST /api/v1/opportunities/{opportunity_id}/estimate-drafts`, and accepting Assumptions
(`POST …/assumptions/{assumption_id}/accept`, `POST …/assumptions/accept-all`), and
exporting the Estimate (Story 8.8, `GET …/estimate/export?format=xlsx|docx`). No endpoint
accepts a total."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.export_content import MEDIA_TYPES
from app.modules.estimates.application.public import (
    AcceptAllResult,
    Assumption,
    EstimateDraft,
    EstimateView,
    ExportFormat,
)
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, or is a sales representative",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    409: "An Estimate draft is already queued or running (`estimate_draft_in_progress`)",
    422: "The Opportunity id is not a UUID (`validation_error`)",
    412: "The Assumption changed since the caller read it (`row_version_mismatch`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["estimates"])


@router.get("/estimate", operation_id="get_estimate", responses=_responses(404, 422))
async def get_estimate(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> EstimateView:
    """The Opportunity's current draft Estimate Version (null before the first) with its
    sections, lines, covered Requirements and server-calculated per-role hours, subtotals and
    totals; and its latest Estimate draft run (null before the first). Anyone who can read
    the Opportunity."""
    return await estimates.get_estimate(uow, actor, opportunity_id)


@router.post(
    "/estimate-drafts",
    operation_id="start_estimate_draft",
    status_code=201,
    responses={
        **_responses(403, 404, 409, 422),
        201: {"description": "The new draft, `queued`"},
    },
)
async def start_estimate_draft(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> EstimateDraft:
    """Queue a new Estimate draft over the Opportunity's active Requirements, e.g. to retry a
    failed one. The owner and collaborators, except sales representatives."""
    return await estimates.start_draft(uow, actor, opportunity_id)


# --- Assumptions (Story 8.4) ----------------------------------------------------------------

_ACCEPT_403 = (
    "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner or a "
    "collaborator, or is a sales representative"
)
_GAP_NOT_OPEN = (
    "The Assumption's Gap is no longer open (`gap_not_open`): it was converted or superseded; "
    "nothing changed"
)
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Assumption as last read (its `row_version`), e.g. `"1"`.',
    ),
]


def _accept_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    responses = _responses(*(c for c in codes if c not in (403, 404, 409)))
    responses[403] = {"description": _ACCEPT_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no "
        "Assumption with this id in its current draft Estimate (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {"description": _GAP_NOT_OPEN, "content": PROBLEM_CONTENT}
    return responses


@router.post(
    "/assumptions/accept-all",
    operation_id="accept_all_assumptions",
    responses={
        **_accept_responses(403, 404, 409, 422),
        200: {"description": "How many Assumptions were accepted"},
    },
)
async def accept_all_assumptions(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> AcceptAllResult:
    """Accept, as the caller, every Assumption of the current draft Estimate not accepted yet,
    converting each one's Gap. All or nothing: if any Gap is no longer open, nothing changes
    (409). No `If-Match`: only unaccepted Assumptions change. The owner and collaborators,
    except sales representatives."""
    return await estimates.accept_all_assumptions(uow, actor, opportunity_id)


@router.post(
    "/assumptions/{assumption_id}/accept",
    operation_id="accept_assumption",
    responses={
        **_accept_responses(403, 404, 409, 412, 422, 428),
        200: {
            "description": "The Assumption",
            "headers": {
                "ETag": {
                    "description": "The Assumption's row version, for `If-Match`.",
                    "schema": {"type": "string"},
                }
            },
        },
    },
)
async def accept_assumption(
    opportunity_id: UUID,
    assumption_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> Assumption:
    """Accept an Assumption of the current draft Estimate as the caller, recording who and
    when, and convert its Gap in the same transaction (409 `gap_not_open` and nothing changes
    if the Gap is no longer open). Already accepted: nothing changes. The owner and
    collaborators, except sales representatives."""
    accepted = await estimates.accept_assumption(
        uow, actor, opportunity_id, assumption_id, if_match
    )
    response.headers["ETag"] = etag(accepted.row_version)
    return accepted


# --- Export (Story 8.8) ---------------------------------------------------------------------

_EXPORT_409 = "The Opportunity has no Estimate Version to export yet (`estimate_not_found`)"
_EXPORT_422 = (
    "The Opportunity id is not a UUID, or `format` is missing or not `xlsx` or `docx` "
    "(`validation_error`)"
)
_FORMAT = Annotated[
    ExportFormat,
    Query(alias="format", description="`xlsx` (a workbook) or `docx` (a document)."),
]


def _export_responses() -> dict[int | str, dict[str, Any]]:
    responses = _responses(403, 404)
    responses[409] = {"description": _EXPORT_409, "content": PROBLEM_CONTENT}
    responses[422] = {"description": _EXPORT_422, "content": PROBLEM_CONTENT}
    responses[200] = {
        "description": "The file, as an attachment named "
        "`{opportunity-slug}-estimate-v{n}.{xlsx|docx}`",
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in MEDIA_TYPES.values()
        },
        "headers": {
            "Content-Disposition": {
                "description": '`attachment; filename="…"`',
                "schema": {"type": "string"},
            }
        },
    }
    return responses


@router.get(
    "/estimate/export",
    operation_id="export_estimate",
    response_class=Response,
    responses=_export_responses(),
)
async def export_estimate(
    opportunity_id: UUID, export_format: _FORMAT, actor: CurrentPrincipal, uow: UoW
) -> Response:
    """Download the current draft Estimate Version as one file: the Estimate (lines by
    section, subtotals, totals), the Assumptions Register and the Clarification Questions,
    each under the header "Estimate v{n} · Draft — not submitted". Built on request from the
    same read models as `GET …/estimate`; every number is the server-calculated one. The
    owner and collaborators, except sales representatives."""
    exported = await estimates.export_estimate(uow, actor, opportunity_id, export_format)
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{exported.file_name}"',
            "Cache-Control": "no-store",
        },
    )
