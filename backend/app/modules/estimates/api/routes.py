"""Estimate routes (Stories 8.1 and 8.4): `GET /api/v1/opportunities/{opportunity_id}/estimate`,
`POST /api/v1/opportunities/{opportunity_id}/estimate-drafts`, accepting Assumptions
(`POST …/assumptions/{assumption_id}/accept`, `POST …/assumptions/accept-all`), editing a
line's hours and role mix (Story 8.2, `PATCH …/estimate-lines/{line_id}`), editing an
Assumption (Story 8.5, `PATCH …/assumptions/{assumption_id}`), converting a Gap to a Risk and
editing a Risk (Story 8.5, `POST …/risks`, `PATCH …/risks/{risk_id}`), and exporting the
Estimate (Story 8.8, `GET …/estimate/export?format=xlsx|docx`). No endpoint accepts a
total."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.export_content import MEDIA_TYPES
from app.modules.estimates.application.public import (
    AcceptAllResult,
    Assumption,
    AssumptionChanges,
    EstimateDraft,
    EstimateLineChanges,
    EstimateView,
    ExportFormat,
    Risk,
    RiskChanges,
    RiskCreate,
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
    409: "An Estimate draft is already queued or running (`estimate_draft_in_progress`), or "
    "the Estimating Agent is disabled in the Agent Registry (`registry_agent_disabled`)",
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


# --- Editing an Assumption, and Risks (Story 8.5) -------------------------------------------

_NOT_DRAFT_409 = (
    "The Estimate Version is not the draft (`estimate_version_not_draft`): a re-draft "
    "replaced it; nothing changed"
)
_STALE_412 = (
    "It changed since the caller read it (`row_version_mismatch`); the `detail` names who "
    "changed it"
)


def _edit_responses(subject: str, rules: str) -> dict[int | str, dict[str, Any]]:
    responses = _responses(428)
    responses[403] = {"description": _ACCEPT_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no "
        f"{subject} with this id in it (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {"description": _NOT_DRAFT_409, "content": PROBLEM_CONTENT}
    responses[412] = {"description": _STALE_412, "content": PROBLEM_CONTENT}
    responses[422] = {
        "description": f"`validation_error`: {rules}, a blank or over-300-character reason "
        "(the `detail` is the sentence to show), an unknown field, or an id that is not a UUID",
        "content": PROBLEM_CONTENT,
    }
    responses[200] = {"description": "The Estimate as it is now, every total recalculated"}
    return responses


_ASSUMPTION_RULES = (
    "wording not 1-500 characters, a Contingency without 0.5-1,000 hours, a Condition with "
    "hours or a line, or a line not of this version"
)


@router.patch(
    "/assumptions/{assumption_id}",
    operation_id="edit_assumption",
    responses=_edit_responses("Assumption", _ASSUMPTION_RULES),
)
async def edit_assumption(
    opportunity_id: UUID,
    assumption_id: UUID,
    body: AssumptionChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _IF_MATCH = None,
) -> EstimateView:
    """Change an Assumption of the draft Estimate: its kind, wording, hours and/or line, with
    a reason. A change clears the acceptance (the Assumption blocks submission again until
    someone accepts it) and is traced with the before and after kind, hours, line and wording
    length. Values equal to the stored ones change nothing, and the acceptance stays. The
    answer is the whole Estimate, so every total comes from the server. The owner and
    collaborators, except sales representatives."""
    return await estimates.edit_assumption(
        uow, actor, opportunity_id, assumption_id, body, if_match
    )


def _create_risk_responses() -> dict[int | str, dict[str, Any]]:
    responses = _responses()
    responses[403] = {"description": _ACCEPT_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no Gap "
        "with this id in it (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {
        "description": "The Opportunity has no draft Estimate (`no_draft_estimate`), or the "
        "Gap is no longer open (`gap_not_open`); nothing changed",
        "content": PROBLEM_CONTENT,
    }
    responses[422] = {
        "description": "`validation_error`: a description not 1-500 characters, an unknown "
        "level or field, or an id that is not a UUID",
        "content": PROBLEM_CONTENT,
    }
    responses[201] = {
        "description": "The new Risk",
        "headers": {
            "ETag": {
                "description": "The Risk's row version, for `If-Match`.",
                "schema": {"type": "string"},
            }
        },
    }
    return responses


@router.post(
    "/risks",
    operation_id="create_risk",
    status_code=201,
    responses=_create_risk_responses(),
)
async def create_risk(
    opportunity_id: UUID, body: RiskCreate, actor: CurrentPrincipal, uow: UoW, response: Response
) -> Risk:
    """Convert an open Gap to a Risk of the draft Estimate, with a description, a likelihood
    and an impact. In the same transaction the Gap becomes `converted` (to `risk`) and the
    draft's unaccepted Assumption proposed for it is removed. Risks are never accepted and
    never block submission. The owner and collaborators, except sales representatives."""
    created = await estimates.create_risk(uow, actor, opportunity_id, body)
    response.headers["ETag"] = etag(created.row_version)
    return created


_RISK_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Risk as last read (its `row_version`), e.g. `"1"`.',
    ),
]


@router.patch(
    "/risks/{risk_id}",
    operation_id="edit_risk",
    responses=_edit_responses("Risk", "a description not 1-500 characters, an unknown level"),
)
async def edit_risk(
    opportunity_id: UUID,
    risk_id: UUID,
    body: RiskChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _RISK_IF_MATCH = None,
) -> EstimateView:
    """Change a Risk of the draft Estimate: its description, likelihood and/or impact, with a
    reason. Traced with the before and after levels and description length. Values equal to
    the stored ones change nothing. The owner and collaborators, except sales
    representatives."""
    return await estimates.edit_risk(uow, actor, opportunity_id, risk_id, body, if_match)


# --- Editing a line (Story 8.2) -------------------------------------------------------------

_LINE_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Estimate line as last read (its `row_version`), e.g. `"1"`.',
    ),
]


def _edit_line_responses() -> dict[int | str, dict[str, Any]]:
    responses = _responses(428)
    responses[403] = {"description": _ACCEPT_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no "
        "Estimate line with this id in it (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {
        "description": "The line's Estimate Version is no longer the draft: a re-draft "
        "replaced it (`estimate_version_not_draft`); nothing changed",
        "content": PROBLEM_CONTENT,
    }
    responses[412] = {
        "description": "The line changed since the caller read it (`row_version_mismatch`); "
        "the `detail` names who changed it",
        "content": PROBLEM_CONTENT,
    }
    responses[422] = {
        "description": "`validation_error`: neither effort nor role mix given, effort not "
        "0-2,000 hours, a role mix that doesn't name every role with whole percentages "
        "adding up to 100, a blank or over-300-character reason (the `detail` is the "
        "sentence to show), an unknown field, or an id that is not a UUID",
        "content": PROBLEM_CONTENT,
    }
    responses[200] = {"description": "The Estimate as it is now, every total recalculated"}
    return responses


@router.patch(
    "/estimate-lines/{line_id}",
    operation_id="edit_estimate_line",
    responses=_edit_line_responses(),
)
async def edit_estimate_line(
    opportunity_id: UUID,
    line_id: UUID,
    body: EstimateLineChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _LINE_IF_MATCH = None,
) -> EstimateView:
    """Change a line of the current draft Estimate's effort hours and/or role mix, with a
    reason. Recorded with who and when, and traced with the before and after values. Values
    equal to the stored ones change nothing. The answer is the whole Estimate, so line role
    hours, subtotals and totals come from the server. The owner and collaborators, except
    sales representatives."""
    return await estimates.edit_line(uow, actor, opportunity_id, line_id, body, if_match)


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
