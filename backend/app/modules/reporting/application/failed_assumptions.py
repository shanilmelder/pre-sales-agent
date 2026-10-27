"""Reports > Estimate vs actual, a group's failed Assumptions (Story 10.4; FR-50, UJ-5).

The "N failed Assumptions" of a group's subline opens this list. It is authorized and
filtered exactly as the report (`estimate_vs_actual`): `reporting.report.read` or 403, the
rows narrowed to the readable Opportunities before anything else, the same filters and the
same group expansion (`filtered_rows`), then the one group asked for (`group_key`, `none`
for the rows without a value). Each distinct failed Assumption is listed once, as the
subline counts it: when several of the group's Actuals name it, the item carries the first
one's line (grid order) and Actual. Read only, one statement.
"""

from typing import Any

import sqlalchemy as sa

from app.modules.identity.application.public import Action, Principal, authorize
from app.modules.opportunities.application import public as opportunities
from app.modules.reporting.application.estimate_vs_actual import (
    ReportFilters,
    applied_filters,
    filtered_rows,
)
from app.modules.reporting.application.models import (
    NO_GROUP_KEY,
    FailedAssumptionItem,
    FailedAssumptionList,
    GroupBy,
)
from app.platform.uow import UnitOfWork

_LIST_SELECT = """
SELECT * FROM (
    SELECT DISTINCT ON (f.assumption_id)
        CAST(g.opportunity_id AS text) AS opportunity_id,
        g.opportunity_title,
        g.line_label,
        f.assumption_kind,
        f.assumption_position,
        f.assumption_wording,
        CAST(f.assumption_amount_hours AS text) AS assumption_amount_hours,
        CAST(f.assumption_id AS text) AS assumption_id,
        f.assumption_version,
        CAST(f.actual_id AS text) AS actual_id
    FROM g JOIN f ON f.actual_id = g.actual_id
    WHERE {group_where}
    ORDER BY f.assumption_id, g.line_label IS NULL, length(g.line_label), g.line_label,
             g.actual_id
) items
ORDER BY lower(opportunity_title), opportunity_id, assumption_position NULLS LAST, assumption_id
"""


def _item(row: Any) -> FailedAssumptionItem:
    position = row.assumption_position
    return FailedAssumptionItem(
        opportunity_id=row.opportunity_id,
        opportunity_title=row.opportunity_title,
        line_label=row.line_label,
        kind=row.assumption_kind,
        position=position,
        label="A?" if position is None else f"A{position}",
        wording=row.assumption_wording or "",
        amount_hours=None
        if row.assumption_amount_hours is None
        else float(row.assumption_amount_hours),
        assumption_id=row.assumption_id,
        assumption_version=int(row.assumption_version),
        actual_id=row.actual_id,
    )


async def failed_assumptions(
    uow: UnitOfWork,
    actor: Principal,
    *,
    group_by: GroupBy,
    group_key: str,
    filters: ReportFilters | None = None,
) -> FailedAssumptionList:
    """A group's failed Assumptions (module docstring)."""
    authorize(actor, Action.REPORTING_REPORT_READ)
    filters = filters or ReportFilters()
    result = FailedAssumptionList(
        group_by=group_by, group_key=group_key, filters=applied_filters(filters), items=[]
    )
    readable = await opportunities.readable_opportunities(uow, actor)
    if not readable.everything and not readable.ids:
        return result
    rows = filtered_rows(readable, filters, group_by)
    if group_key == NO_GROUP_KEY:
        group_where = "g.group_key IS NULL"
    else:
        group_where = "g.group_key = :group_key"
        rows.params["group_key"] = group_key
    statement = rows.statement(_LIST_SELECT.format(group_where=group_where))
    await uow.session.execute(sa.text("SET LOCAL jit = off"))  # as the report
    found = (await uow.session.execute(statement)).all()
    result.items = [_item(row) for row in found]
    return result
