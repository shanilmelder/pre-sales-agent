"""Actuals routes (Story 10.1), under `/api/v1/opportunities/{opportunity_id}`:

- `GET …/actuals`: the Actuals tab (anyone who can read the Opportunity), with its `ETag`;
- `POST …/actuals` with `If-Match` the tab's ETag: **Save Actuals** (records and corrections);
- `POST …/actuals/{actual_id}/corrections` with `If-Match` the Actual's version: correct it;
- `POST …/actuals/delivery/close` with `If-Match` the tab's ETag: **Close delivery**.

Writes are for delivery managers only; everyone else who can read the Opportunity gets 403.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.modules.actuals.application import public as actuals
from app.modules.actuals.application.public import (
    ActualCorrection,
    ActualsSave,
    ActualsView,
    SavedActuals,
)
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
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
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW, response: Response
) -> ActualsView:
    """The Actuals tab: every Baseline line with its estimate, current Actual and
    server-calculated variance, Unplanned work, totals, the Baseline version's Assumptions
    Register, and whether the caller may record Actuals or close delivery. Anyone who can
    read the Opportunity."""
    view = await actuals.get_actuals(uow, actor, opportunity_id)
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
