"""Reports routes (Story 10.3), under `/api/v1/reports`:

- `GET /reports/estimate-vs-actual`: estimate versus actual across the Opportunities the
  caller can read, grouped and filtered.
- `GET /reports/failed-assumptions` (Story 10.4): one group's failed Assumptions, under the
  same filters.

Holders of `reporting.report.read` only (the Head of Delivery and platform administrators);
everyone else gets 403.
"""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.reporting.application import public as reporting
from app.modules.reporting.application.public import (
    EstimateVsActualReport,
    FailedAssumptionList,
    GroupBy,
    ReportFilters,
    VarianceCause,
)
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PRODUCT_MAX = 200
GROUP_KEY_MAX = 200

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"description": description, "content": PROBLEM_CONTENT}
    for code, description in (
        (401, "No valid access token (`token_missing`, `token_expired`, `token_invalid`)"),
        (403, "The caller lacks `reporting.report.read` (`forbidden`)"),
        (422, "An invalid parameter (`validation_error`), e.g. `closed_from` after `closed_to`"),
        (503, "Sign-in service unavailable (`auth_unavailable`)"),
    )
}

router = APIRouter(prefix="/reports", tags=["reporting"])


@dataclass(frozen=True, slots=True)
class _Filters:
    filters: ReportFilters


async def _filters(
    product: Annotated[
        str | None,
        Query(
            description="Only Opportunities with this product (trimmed, ignoring case). Blank "
            "is ignored.",
            max_length=PRODUCT_MAX,
        ),
    ] = None,
    work_package_id: Annotated[
        UUID | None, Query(description="Only Actuals tagged with this Work Package.")
    ] = None,
    integration_type_id: Annotated[
        UUID | None,
        Query(description="Story 10.4: only Actuals tagged with this Integration Type."),
    ] = None,
    cause: Annotated[
        VarianceCause | None, Query(description="Only Actuals with this variance cause.")
    ] = None,
    closed_from: Annotated[
        date | None,
        Query(description="Only Opportunities whose delivery closed on or after this date."),
    ] = None,
    closed_to: Annotated[
        date | None,
        Query(description="Only Opportunities whose delivery closed on or before this date."),
    ] = None,
    include_milestones: Annotated[
        bool, Query(description="Count milestone Actuals too (default: final Actuals only).")
    ] = False,
) -> _Filters:
    if closed_from is not None and closed_to is not None and closed_from > closed_to:
        raise RequestValidationError(
            [
                {"loc": ("query", name), "msg": "invalid", "type": "value_error"}
                for name in ("closed_from", "closed_to")
            ]
        )
    trimmed = product.strip() if product is not None else None
    return _Filters(
        ReportFilters(
            product=trimmed or None,
            work_package_id=work_package_id,
            integration_type_id=integration_type_id,
            cause=cause,
            closed_from=closed_from,
            closed_to=closed_to,
            include_milestones=include_milestones,
        )
    )


Filters = Annotated[_Filters, Depends(_filters)]


@router.get(
    "/estimate-vs-actual", operation_id="get_estimate_vs_actual_report", responses=_RESPONSES
)
async def get_estimate_vs_actual_report(
    actor: CurrentPrincipal,
    uow: UoW,
    filters: Filters,
    group_by: Annotated[
        GroupBy, Query(description="How the table's rows are grouped.")
    ] = GroupBy.INTEGRATION_TYPE,
) -> EstimateVsActualReport:
    """Estimate versus actual: the KPIs (closed Opportunities, total variance, failed
    Assumptions by kind), the groups (estimate and actual hours, variance with its tone and
    bar, main cause, failed Assumptions) and each group's Opportunities per Estimate Version,
    with the Baseline flag. Only the Opportunities the caller can read count. Every figure is
    computed on the server."""
    return await reporting.estimate_vs_actual(
        uow, actor, group_by=group_by, filters=filters.filters
    )


@router.get(
    "/failed-assumptions", operation_id="get_failed_assumptions_report", responses=_RESPONSES
)
async def get_failed_assumptions_report(
    actor: CurrentPrincipal,
    uow: UoW,
    filters: Filters,
    group_key: Annotated[
        str,
        Query(
            min_length=1,
            max_length=GROUP_KEY_MAX,
            description="The group's `key` from the report (`none`: the rows without a value).",
        ),
    ],
    group_by: Annotated[
        GroupBy, Query(description="How the report's rows are grouped.")
    ] = GroupBy.INTEGRATION_TYPE,
) -> FailedAssumptionList:
    """Story 10.4: the distinct failed Assumptions the group's Actuals name (the report's
    "N failed Assumptions"), under the same filters and visibility as the report: each with
    its Opportunity, line, kind, "A{n}", wording, Assumption version and Actual. An unknown
    group gives an empty list."""
    return await reporting.failed_assumptions(
        uow, actor, group_by=group_by, group_key=group_key, filters=filters.filters
    )
