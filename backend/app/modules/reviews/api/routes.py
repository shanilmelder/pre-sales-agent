"""Review Request routes (Story 9.1), under `/api/v1/opportunities/{opportunity_id}`:

- `GET …/review-requests?version_id=`: the version's requests (default: the current
  Estimate Version), the Assessments a request may target, and `can_create`;
- `GET …/review-requests/reviewer-candidates?review_type=&q=`: users holding the review
  type's role, minus the version's author;
- `POST …/review-requests` with `If-Match` the Estimate Version's ETag: send requests;
- `POST …/review-requests/{request_id}/cancel` with `If-Match` the request's ETag: cancel.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.modules.identity.application.public import (
    SEARCH_MAX_QUERY,
    CurrentPrincipal,
    UserSearchResult,
)
from app.modules.reviews.application import public as reviews
from app.modules.reviews.application.public import (
    CreatedReviewRequests,
    ReviewRequestCancel,
    ReviewRequestCreate,
    ReviewRequestsView,
    ReviewRequestView,
    ReviewType,
)
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, is a sales representative or a reviewer collaborator",
    404: "No Opportunity with this id, or the caller may not see it, or no Estimate Version "
    "or Review Request with this id in it (`not_found`)",
    412: "The Estimate Version or Review Request changed since the caller read it "
    "(`row_version_mismatch`)",
    422: "`validation_error`: a malformed id or body",
    428: "No `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(
    *codes: int, described: dict[int, str] | None = None
) -> dict[int | str, dict[str, Any]]:
    """The problem responses: `codes` with their usual description, `described` with its
    own."""
    responses: dict[int | str, dict[str, Any]] = {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }
    for code, text in (described or {}).items():
        responses[code] = {"description": text, "content": PROBLEM_CONTENT}
    return responses


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["reviews"])

_VERSION_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description="The ETag of the Estimate Version as last read (its `row_version`), "
        'e.g. `"2"`.',
    ),
]
_REQUEST_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Review Request as last read (its `row_version`), e.g. `"1"`.',
    ),
]


@router.get("/review-requests", operation_id="list_review_requests", responses=_responses(404, 422))
async def list_review_requests(
    opportunity_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    version_id: Annotated[UUID | None, Query()] = None,
) -> ReviewRequestsView:
    """The Review Requests of an Estimate Version (default: the current one), oldest first,
    with reviewer and sender names and statuses; the current Assessments a new request may
    target; and whether the caller may send requests now. Anyone who can read the
    Opportunity."""
    return await reviews.list_review_requests(uow, actor, opportunity_id, version_id)


@router.get(
    "/review-requests/reviewer-candidates",
    operation_id="list_reviewer_candidates",
    responses=_responses(403, 404, 422),
)
async def list_reviewer_candidates(
    opportunity_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    review_type: ReviewType,
    q: Annotated[str, Query(max_length=SEARCH_MAX_QUERY)] = "",
    version_id: Annotated[UUID | None, Query()] = None,
) -> UserSearchResult:
    """Users who hold the review type's role (engineering, PM or security reviewer), except
    the Estimate Version's author, whose name or email contains `q` (all of them for a blank
    `q`), by name. Only those who may send Review Requests on the Opportunity."""
    return await reviews.reviewer_candidates(uow, actor, opportunity_id, review_type, q, version_id)


@router.post(
    "/review-requests",
    operation_id="create_review_requests",
    status_code=201,
    responses={
        **_responses(
            403,
            404,
            412,
            428,
            described={
                409: "The version is a draft (`estimate_version_not_submitted`), superseded "
                "(`estimate_version_superseded`) or rejected (`estimate_version_rejected`), or a "
                "reviewer already has a pending request of that type on the same target "
                "(`review_request_duplicate`); nothing was written",
                422: "`reviewer_not_authorized_for_type`: a reviewer lacks the review type's role; "
                "`author_cannot_review`: the version's author was named; `validation_error`: no "
                "reviewer, a reviewer named twice, a message over 2,000 characters, or an "
                "Assessment that is not current at that version. The `detail` is the sentence "
                "to show",
            },
        ),
        201: {
            "description": "The requests sent, and the version's new status",
            "headers": {
                "ETag": {
                    "description": "The Estimate Version's row version, for `If-Match`.",
                    "schema": {"type": "string"},
                }
            },
        },
    },
)
async def create_review_requests(
    opportunity_id: UUID,
    body: ReviewRequestCreate,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _VERSION_IF_MATCH = None,
) -> CreatedReviewRequests:
    """Send Review Requests for a submitted (or in-review) Estimate Version: one per reviewer
    and picked Assessment, or one per reviewer for the whole version. The version becomes
    `in_review` and each reviewer can read the Opportunity. The owner and collaborators,
    except sales representatives."""
    created = await reviews.create_from_body(uow, actor, opportunity_id, body, if_match)
    response.headers["ETag"] = etag(created.version_row_version)
    return created


@router.post(
    "/review-requests/{request_id}/cancel",
    operation_id="cancel_review_request",
    responses={
        **_responses(
            404,
            412,
            428,
            described={
                403: "Not allowed (`forbidden`): only the request's sender or the Opportunity's "
                "owner, never a sales representative",
                409: "The request is no longer pending (`review_request_not_pending`)",
                422: "`validation_error`: a blank or over-1,000-character reason; the `detail` is "
                "the sentence to show",
            },
        ),
        200: {
            "description": "The cancelled request",
            "headers": {
                "ETag": {
                    "description": "The request's row version.",
                    "schema": {"type": "string"},
                }
            },
        },
    },
)
async def cancel_review_request(
    opportunity_id: UUID,
    request_id: UUID,
    body: ReviewRequestCancel,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _REQUEST_IF_MATCH = None,
) -> ReviewRequestView:
    """Cancel a pending Review Request with a reason. The reviewer loses read access once
    they have no pending request left on the Opportunity; the version goes back to
    `submitted` once none is left for it."""
    view = await reviews.cancel_review_request(
        uow, actor, opportunity_id, request_id, body, if_match
    )
    response.headers["ETag"] = etag(view.row_version)
    return view
