"""Estimate routes (Stories 8.1 and 8.4): `GET /api/v1/opportunities/{opportunity_id}/estimate`,
`POST /api/v1/opportunities/{opportunity_id}/estimate-drafts`, accepting Assumptions
(`POST …/assumptions/{assumption_id}/accept`, `POST …/assumptions/accept-all`), editing a
line's hours and role mix (Story 8.2, `PATCH …/estimate-lines/{line_id}`), editing an
Assumption (Story 8.5, `PATCH …/assumptions/{assumption_id}`), converting a Gap to a Risk and
editing a Risk (Story 8.5, `POST …/risks`, `PATCH …/risks/{risk_id}`), exporting the
Estimate (Story 8.8, `GET …/estimate/export?format=xlsx|docx`), and the submission blockers
and submitting a version (Story 8.6, `GET …/submission-blockers`,
`POST …/estimate/versions/{version_id}/submit`), Story 9.4's **New version**
(`POST …/estimate-versions/{version_id}/new-version`), and Story 9.7's Baseline
(`POST …/estimate-versions/{version_id}/baseline`, `GET …/{version_id}/approvers`), the
version list (`GET …/estimate-versions`) and an earlier version read only
(`GET …/estimate?version=n`); Story 9.9's lineage (`GET …/estimate-lines/{line_id}/lineage`,
`GET …/assumptions/{assumption_id}/lineage`) and any-two-versions compare
(`GET …/estimate-versions/compare?from=n&to=m`). No endpoint accepts a total."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.export_content import MEDIA_TYPES
from app.modules.estimates.application.public import (
    AcceptAllResult,
    Assumption,
    AssumptionChanges,
    AssumptionLineage,
    BaselineApproval,
    BaselineSet,
    Blocker,
    CreatedVersion,
    EstimateDraft,
    EstimateLineChanges,
    EstimateView,
    ExportFormat,
    LineLineage,
    NewVersionCreate,
    Risk,
    RiskChanges,
    RiskCreate,
    SubmissionBlockers,
    SubmissionBlockersView,
    SubmittedVersion,
    VersionComparison,
    VersionListItem,
)
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.concurrency import etag
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.storage import BlobStore
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
async def get_estimate(
    opportunity_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    version: Annotated[
        int | None,
        Query(
            ge=1,
            le=2**31 - 1,
            description="Story 9.7: an Estimate Version's number, to read that version (read "
            "only unless it is the current one; 404 when there is none). Without it, the "
            "current version.",
        ),
    ] = None,
) -> EstimateView:
    """The Opportunity's current Estimate Version (its draft, else its latest submitted one;
    null before the first) with its sections, lines, covered Requirements and
    server-calculated per-role hours, subtotals and totals, and its submission blockers; and
    its latest Estimate draft run (null before the first). Story 9.7: with the current
    Baseline, and `?version=n` reads an earlier version read only. Anyone who can read the
    Opportunity."""
    return await estimates.get_estimate(uow, actor, opportunity_id, version)


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
    responses[409] = {
        "description": _GAP_NOT_OPEN + "; or the current Estimate Version was submitted "
        "(`estimate_version_not_draft`)",
        "content": PROBLEM_CONTENT,
    }
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
        "replaced it, or it was submitted (`estimate_version_not_draft`); nothing changed",
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


# --- Submission blockers and submit (Story 8.6) ---------------------------------------------


class SubmissionBlockedProblem(Problem):
    """The submit 409 body: for `estimate_version_blocked`, the problem with the blockers
    found at the time of the request in its `blockers` extension member; absent for
    `estimate_version_not_draft`."""

    blockers: SubmissionBlockers | None = None


# Inline, with refs to the components the read models already publish (`SubmissionBlockers`
# is in `EstimateView`).
_BLOCKED_SCHEMA = {
    k: v
    for k, v in SubmissionBlockedProblem.model_json_schema(
        ref_template="#/components/schemas/{model}"
    ).items()
    if k != "$defs"
}

_VERSION_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description="The ETag of the Estimate Version as last read (its `row_version`), "
        'e.g. `"1"`.',
    ),
]


@router.get(
    "/submission-blockers",
    operation_id="get_submission_blockers",
    responses=_responses(404, 422),
)
async def get_submission_blockers(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> SubmissionBlockersView:
    """What stands between the Opportunity's current Estimate Version and its submission
    (the one check, AD-27): open Gaps and Unknowns, unaccepted Assumptions, open Conflicts,
    open critical Findings and uncovered Requirements, each with a link to its subject;
    `to_baseline` stays empty until Review Requests exist. With the current version and
    whether the caller may submit it. Anyone who can read the Opportunity."""
    return await estimates.submission_blockers_view(uow, actor, opportunity_id)


def _submit_responses() -> dict[int | str, dict[str, Any]]:
    responses = _responses(422, 428)
    responses[403] = {"description": _ACCEPT_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no "
        "Estimate Version with this id in it (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {
        "description": "The version still has submission blockers "
        "(`estimate_version_blocked`, listed in `blockers`), or it is not the draft "
        "(`estimate_version_not_draft`); nothing changed",
        "content": {PROBLEM_JSON: {"schema": _BLOCKED_SCHEMA}},
    }
    responses[412] = {
        "description": "The version changed since the caller read it (`row_version_mismatch`)",
        "content": PROBLEM_CONTENT,
    }
    responses[200] = {
        "description": "The submitted version",
        "headers": {
            "ETag": {
                "description": "The version's new row version.",
                "schema": {"type": "string"},
            }
        },
    }
    return responses


@router.post(
    "/estimate/versions/{version_id}/submit",
    operation_id="submit_estimate_version",
    responses=_submit_responses(),
)
async def submit_estimate_version(
    opportunity_id: UUID,
    version_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _VERSION_IF_MATCH = None,
) -> SubmittedVersion:
    """Submit the draft Estimate Version. The submission blockers are checked again under
    the Opportunity's lock: any left is 409 `estimate_version_blocked` and the version stays
    a draft. Earlier submitted versions become superseded. Submitted versions can't be
    edited. The owner and collaborators, except sales representatives."""
    submitted = await estimates.submit_version(uow, actor, opportunity_id, version_id, if_match)
    response.headers["ETag"] = etag(submitted.row_version)
    return submitted


def _new_version_responses() -> dict[int | str, dict[str, Any]]:
    responses = _responses(422)
    responses[403] = {"description": _ACCEPT_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no "
        "Estimate Version with this id in it (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {
        "description": "The base is neither rejected nor approved "
        "(`estimate_version_not_decided`), or the Opportunity already has a draft "
        "(`estimate_draft_exists`); nothing changed",
        "content": PROBLEM_CONTENT,
    }
    responses[201] = {
        "description": "The new draft version",
        "headers": {
            "ETag": {
                "description": "The new version's row version.",
                "schema": {"type": "string"},
            }
        },
    }
    return responses


@router.post(
    "/estimate-versions/{version_id}/new-version",
    operation_id="create_estimate_version",
    status_code=201,
    responses=_new_version_responses(),
)
async def create_estimate_version(
    opportunity_id: UUID,
    version_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    body: NewVersionCreate | None = None,
) -> CreatedVersion:
    """Story 9.4: start a new draft Estimate Version from a rejected or approved one, with a
    copy of its lines and its Assumptions and Risks carried. The base keeps its status until
    the new draft is submitted. The owner and collaborators, except sales representatives."""
    reason = None if body is None else body.reason
    created = await estimates.create_version(uow, actor, opportunity_id, version_id, reason)
    response.headers["ETag"] = etag(created.row_version)
    return created


# --- the Baseline and the version list (Story 9.7) ------------------------------------------

_BASELINE_403 = (
    "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner or a "
    "collaborator, is a sales representative, or is not a person (an agent or the system)"
)


def _baseline_responses() -> dict[int | str, dict[str, Any]]:
    responses = _responses(422, 428)
    responses[403] = {"description": _BASELINE_403, "content": PROBLEM_CONTENT}
    responses[404] = {
        "description": "No Opportunity with this id, or the caller may not see it, or no "
        "Estimate Version with this id in it (`not_found`)",
        "content": PROBLEM_CONTENT,
    }
    responses[409] = {
        "description": "The version isn't a newer approved version than the current Baseline "
        "(`baseline_not_newer`), or it isn't approved or still has blockers to Baseline "
        "(`baseline_blocked`, each listed by kind in `blockers`); nothing changed",
        "content": {PROBLEM_JSON: {"schema": _BASELINE_BLOCKED_SCHEMA}},
    }
    responses[412] = {
        "description": "The version changed since the caller read it (`row_version_mismatch`)",
        "content": PROBLEM_CONTENT,
    }
    responses[201] = {"description": "The Baseline just set"}
    return responses


class BaselineBlockedProblem(Problem):
    """The Set Baseline 409 body: for `baseline_blocked`, the problem with each blocker to
    Baseline found at the time of the request in its `blockers` extension member; absent for
    `baseline_not_newer`."""

    blockers: list[Blocker] | None = None


_BASELINE_BLOCKED_SCHEMA = {
    k: v
    for k, v in BaselineBlockedProblem.model_json_schema(
        ref_template="#/components/schemas/{model}"
    ).items()
    if k != "$defs"
}


@router.post(
    "/estimate-versions/{version_id}/baseline",
    operation_id="set_estimate_baseline",
    status_code=201,
    responses=_baseline_responses(),
)
async def set_estimate_baseline(
    opportunity_id: UUID,
    version_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    if_match: _VERSION_IF_MATCH = None,
) -> BaselineSet:
    """Story 9.7: set the approved Estimate Version as the Opportunity's Baseline. It must be
    approved, have no blockers to Baseline (checked again under the Opportunity's lock) and,
    when a Baseline exists, be numbered above it. Traced with its approvers; it can't be
    undone, only replaced by a newer approved version. The owner and collaborators, except
    sales representatives; people only."""
    return await estimates.set_baseline(uow, actor, opportunity_id, version_id, if_match)


@router.get(
    "/estimate-versions/compare",
    operation_id="compare_estimate_versions",
    responses={
        **_responses(422),
        404: {
            "description": "No Opportunity with this id, or the caller may not see it, or no "
            "Estimate Version with one of these numbers in it (`not_found`)",
            "content": PROBLEM_CONTENT,
        },
    },
)
async def compare_estimate_versions(
    opportunity_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    from_: Annotated[
        int,
        Query(
            alias="from",
            ge=1,
            le=2**31 - 1,
            description="The base Estimate Version's number.",
        ),
    ],
    to: Annotated[
        int,
        Query(ge=1, le=2**31 - 1, description="The Estimate Version compared with the base."),
    ],
) -> VersionComparison:
    """Story 9.9: any two Estimate Versions of the Opportunity, `from` (the base) against
    `to`: the added, removed and changed lines with their deltas, each side's total and the
    delta, the Assumptions and Risks added, removed or changed, and **why it changed**: the
    trace events between the two versions' creation (line edits, versions created,
    Conflicts resolved or escalated, Challenges, review decisions, Assessments completed,
    Findings overridden or resolved, Assumption and Risk changes, Gaps converted). The same
    number twice is 422. Anyone who can read the Opportunity."""
    return await estimates.compare_any(uow, actor, opportunity_id, from_, to)


@router.get(
    "/estimate-lines/{line_id}/lineage",
    operation_id="get_estimate_line_lineage",
    responses={
        **_responses(422),
        404: {
            "description": "No Opportunity with this id, or the caller may not see it, or no "
            "Estimate line with this id in it (`not_found`)",
            "content": PROBLEM_CONTENT,
        },
    },
)
async def get_estimate_line_lineage(
    opportunity_id: UUID, line_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> LineLineage:
    """Story 9.9: what is behind the Estimate line, derived and read only: the Requirements it
    covers at their cited versions (with Evidence), the Findings and effort entries of its
    version's assessment run that cite them, human decisions (Conflict resolutions, Finding
    overrides and resolutions), its Contingencies, its edits and those of the lines it was
    carried from, and the Challenges and review decisions on its version. Each item says
    which version it cites and whether it was superseded. Anyone who can read the
    Opportunity."""
    return await estimates.get_line_lineage(uow, actor, opportunity_id, line_id)


@router.get(
    "/assumptions/{assumption_id}/lineage",
    operation_id="get_assumption_lineage",
    responses={
        **_responses(422),
        404: {
            "description": "No Opportunity with this id, or the caller may not see it, or no "
            "Assumption with this id in it (`not_found`)",
            "content": PROBLEM_CONTENT,
        },
    },
)
async def get_assumption_lineage(
    opportunity_id: UUID,
    assumption_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    request: Request,
) -> AssumptionLineage:
    """Story 9.9: the Assumption's chain, oldest first: its origin (a Gap, an Unknown or a
    Finding), the Clarification Question, the recorded answer with its Source passage, the
    conversion and the acceptance (who and when). A step that never happened is left out; a
    sales representative sees a question only once approved or sent. Anyone who can read the
    Opportunity."""
    settings: Settings = request.app.state.settings
    return await estimates.get_assumption_lineage(
        uow, actor, opportunity_id, assumption_id, store=BlobStore(settings.storage_dir)
    )


@router.get(
    "/estimate-versions/{version_id}/approvers",
    operation_id="list_estimate_version_approvers",
    responses={
        **_responses(422),
        404: {
            "description": "No Opportunity with this id, or the caller may not see it, or no "
            "Estimate Version with this id in it (`not_found`)",
            "content": PROBLEM_CONTENT,
        },
    },
)
async def list_estimate_version_approvers(
    opportunity_id: UUID, version_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> list[BaselineApproval]:
    """Story 9.7: the Review Requests behind the version (not cancelled, oldest first), each
    with who decided, the review type and when, for the Set Baseline dialog. Anyone who can
    read the Opportunity."""
    return await estimates.version_approvers(uow, actor, opportunity_id, version_id)


@router.get(
    "/estimate-versions",
    operation_id="list_estimate_versions",
    responses=_responses(404, 422),
)
async def list_estimate_versions(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> list[VersionListItem]:
    """Story 9.7: every Estimate Version of the Opportunity, the Baseline first, then newest
    first, with its status, who created it and when, and the reason for a **New version**.
    Anyone who can read the Opportunity."""
    return await estimates.list_versions(uow, actor, opportunity_id)
