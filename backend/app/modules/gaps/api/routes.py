"""Gap routes (Story 4.3): `GET /api/v1/opportunities/{opportunity_id}/gaps` and
`POST /api/v1/opportunities/{opportunity_id}/gap-detections`; Story 4.5: editing and approving
Clarification Questions under `…/clarification-questions`."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.modules.gaps.application import public as gaps
from app.modules.gaps.application.public import (
    ApproveAllResult,
    ClarificationQuestion,
    Detection,
    GapList,
    QuestionChanges,
    QuestionVersion,
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
    409: "A Gap detection is already queued or running (`gap_detection_in_progress`)",
    422: "The Opportunity id is not a UUID (`validation_error`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["gaps"])


@router.get("/gaps", operation_id="list_gaps", responses=_responses(404, 422))
async def list_gaps(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> GapList:
    """The Opportunity's open Gaps, high impact first, then medium, then low (oldest first
    within an impact), then its converted Gaps in the same order, each with the Requirements
    it relates to and its Clarification Question; and its latest Gap detection (null before
    the first). Anyone who can read the Opportunity; a sales representative sees only
    approved questions."""
    return await gaps.list_gaps(uow, actor, opportunity_id)


@router.post(
    "/gap-detections",
    operation_id="start_gap_detection",
    status_code=201,
    responses={
        **_responses(403, 404, 409, 422),
        201: {"description": "The new detection, `queued`"},
    },
)
async def start_gap_detection(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> Detection:
    """Queue a new Gap detection over the Opportunity's active Requirements, e.g. to retry a
    failed one. The owner and collaborators, except sales representatives."""
    return await gaps.start_detection(uow, actor, opportunity_id)


# --- editing and approving Clarification Questions (Story 4.5) ------------------------------

_QUESTION_DESCRIBED: dict[int, str] = {
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, or is a sales representative",
    404: "No Opportunity with this id, or the caller may not see it, or no Clarification "
    "Question with this id in it (`not_found`)",
    409: "The question's Gap is not open: it was converted or superseded (`gap_not_open`)",
    412: "The question changed since the caller read it (`row_version_mismatch`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
}
_ETAG_HEADER = {
    "ETag": {
        "description": "The question's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the question as last read (its `row_version`), e.g. `"3"`.',
    ),
]


def _question_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    responses = _responses()
    for code in codes:
        responses[code] = {"description": _QUESTION_DESCRIBED[code], "content": PROBLEM_CONTENT}
    return responses


def _with_etag(response: Response, question: ClarificationQuestion) -> ClarificationQuestion:
    response.headers["ETag"] = etag(question.row_version)
    return question


_PATCH_RESPONSES = _question_responses(403, 404, 409, 412, 428)
_PATCH_RESPONSES[422] = {
    "description": "`validation_error`: the text is blank or longer than 1,000 characters, or "
    "the topic blank or longer than 80, once trimmed (the `detail` is the sentence to show), "
    "an unknown field, or an id that is not a UUID",
    "content": PROBLEM_CONTENT,
}
_ID_422 = {"description": "An id is not a UUID (`validation_error`)", "content": PROBLEM_CONTENT}


_APPROVE_ALL_RESPONSES = _question_responses(403, 412)
_APPROVE_ALL_RESPONSES[404] = {
    "description": "No Opportunity with this id, or the caller may not see it (`not_found`)",
    "content": PROBLEM_CONTENT,
}
_APPROVE_ALL_RESPONSES[412] = {
    "description": "The listed questions differ from the drafted questions of open Gaps: one "
    "changed (row version), is no longer drafted, or a drafted one isn't listed "
    "(`row_version_mismatch`); nothing is approved",
    "content": PROBLEM_CONTENT,
}
_APPROVE_ALL_RESPONSES[422] = {
    "description": "An id is not a UUID, or the body is not a list of `{id, row_version}` "
    "(`validation_error`)",
    "content": PROBLEM_CONTENT,
}


@router.post(
    "/clarification-questions/approve-all",
    operation_id="approve_all_clarification_questions",
    responses={
        **_APPROVE_ALL_RESPONSES,
        200: {"description": "How many questions were approved"},
    },
)
async def approve_all_clarification_questions(
    opportunity_id: UUID,
    body: list[QuestionVersion],
    actor: CurrentPrincipal,
    uow: UoW,
) -> ApproveAllResult:
    """Approve exactly the drafted Clarification Questions the client shows (`id` and
    `row_version` each), all or nothing. If one changed or is no longer drafted, or a drafted
    question of an open Gap isn't listed, 412 and nothing is approved. The owner and
    collaborators, except sales representatives."""
    return await gaps.approve_all(uow, actor, opportunity_id, body)


@router.patch(
    "/clarification-questions/{question_id}",
    operation_id="edit_clarification_question",
    responses={
        **_PATCH_RESPONSES,
        200: {"description": "The question", "headers": _ETAG_HEADER},
    },
)
async def edit_clarification_question(
    opportunity_id: UUID,
    question_id: UUID,
    body: QuestionChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> ClarificationQuestion:
    """Change a Clarification Question's text and/or topic. A change marks it edited by a
    person (so a later Gap detection keeps it) and returns an approved question to drafted.
    Nothing changed: nothing is written. Only questions of open Gaps. The owner and
    collaborators, except sales representatives."""
    changed = await gaps.edit_question(uow, actor, opportunity_id, question_id, body, if_match)
    return _with_etag(response, changed)


_APPROVE_RESPONSES = _question_responses(403, 404, 409, 412, 428)
_APPROVE_RESPONSES[422] = _ID_422


@router.post(
    "/clarification-questions/{question_id}/approve",
    operation_id="approve_clarification_question",
    responses={
        **_APPROVE_RESPONSES,
        200: {"description": "The question", "headers": _ETAG_HEADER},
    },
)
async def approve_clarification_question(
    opportunity_id: UUID,
    question_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> ClarificationQuestion:
    """Approve a Clarification Question as the caller (so a later Gap detection keeps it).
    Already approved: nothing changes. Only questions of open Gaps. The owner and
    collaborators, except sales representatives."""
    approved = await gaps.approve_question(uow, actor, opportunity_id, question_id, if_match)
    return _with_etag(response, approved)
