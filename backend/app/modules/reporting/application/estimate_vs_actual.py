"""Reports > Estimate vs actual (Story 10.3; FR-50).

Aggregated in SQL over the read-only `reporting_estimate_vs_actual` and
`reporting_failed_assumptions` views, in one statement per request:

1. `authorize(actor, reporting.report.read)`: the Head of Delivery and platform
   administrators; everyone else gets 403.
2. The rows are restricted to the Opportunities the caller can read
   (`opportunities.readable_opportunities`) and materialized once (`r_all`, which also feeds
   the filter options), then narrowed to final Actuals (milestones only with
   `include_milestones`) and the filters (`r`), before anything is summed.
3. Each row is expanded into its groups (an Actual with two Integration Types, or an
   Opportunity with two products, is in both groups) and summed per group, Opportunity and
   Estimate Version, and cause. The KPIs are summed over the distinct rows, so each Actual
   counts once.
4. Variance, colour tone, bar and main cause come from `reporting.domain.variance`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.modules.identity.application.public import Action, Principal, authorize
from app.modules.opportunities.application import public as opportunities
from app.modules.reporting.application.models import (
    NO_GROUP_KEY,
    AppliedFilters,
    Calibration,
    CauseRef,
    EstimateVsActualReport,
    FailedKindCount,
    GroupBy,
    GroupOpportunity,
    ReportOptions,
    ReportVarianceView,
    VarianceGroup,
    VarianceKpis,
    WorkPackageOption,
)
from app.modules.reporting.domain.variance import (
    CALIBRATION_THRESHOLD,
    CAUSE_LABELS,
    CauseStats,
    VarianceCause,
    calibration_message,
    main_cause,
    report_variance,
)
from app.platform.uow import UnitOfWork

VIEW = "reporting_estimate_vs_actual"
FAILED_VIEW = "reporting_failed_assumptions"
ZERO = Decimal(0)

NO_GROUP_LABELS: dict[GroupBy, str] = {
    GroupBy.INTEGRATION_TYPE: "No Integration Type",
    GroupBy.OPPORTUNITY: "No Opportunity",
    GroupBy.PRODUCT: "No product",
    GroupBy.WORK_PACKAGE: "No Work Package",
    GroupBy.CAUSE: "No cause",
}
FAILED_KIND_LABELS = {
    "condition": ("Condition", "Conditions"),
    "contingency": ("Contingency", "Contingencies"),
}

# Each grouping as a LATERAL producing (group_key, group_label) per row of `r`; a row with no
# value gets one NULL key.
_GROUP_LATERAL: dict[GroupBy, str] = {
    GroupBy.INTEGRATION_TYPE: (
        "SELECT CAST(t.id AS text) AS group_key, t.name AS group_label "
        "FROM unnest(r.integration_type_ids, r.integration_type_names) AS t(id, name) "
        "UNION ALL SELECT NULL, NULL WHERE cardinality(r.integration_type_ids) = 0"
    ),
    GroupBy.PRODUCT: (
        "SELECT p AS group_key, p AS group_label FROM unnest(r.products) AS p "
        "UNION ALL SELECT NULL, NULL WHERE cardinality(r.products) = 0"
    ),
    GroupBy.OPPORTUNITY: (
        "SELECT CAST(r.opportunity_id AS text) AS group_key, r.opportunity_title AS group_label"
    ),
    GroupBy.WORK_PACKAGE: (
        "SELECT CAST(r.work_package_id AS text) AS group_key, r.work_package_name AS group_label"
    ),
    GroupBy.CAUSE: "SELECT r.variance_cause AS group_key, CAST(NULL AS text) AS group_label",
}


@dataclass(frozen=True, slots=True)
class ReportFilters:
    product: str | None = None
    work_package_id: UUID | None = None
    cause: VarianceCause | None = None
    closed_from: date | None = None
    closed_to: date | None = None
    include_milestones: bool = False


# Every part of the report is one JSON column over the materialized CTEs, so the view is
# evaluated once per request. Hours are cast to text so they arrive as exact Decimals.
_REPORT_SELECT = """
SELECT
    EXISTS (SELECT 1 FROM r_all) AS has_actuals,
    (SELECT COALESCE(jsonb_agg(DISTINCT btrim(p)), '[]')
     FROM r_all CROSS JOIN LATERAL unnest(r_all.products) AS p
     WHERE btrim(p) <> '') AS products,
    (SELECT COALESCE(jsonb_agg(jsonb_build_object('id', w.id, 'name', w.name)), '[]')
     FROM (SELECT DISTINCT CAST(work_package_id AS text) AS id, work_package_name AS name
           FROM r_all WHERE work_package_id IS NOT NULL) w) AS packages,
    (SELECT jsonb_build_object(
         'n', count(*),
         'closed', count(DISTINCT opportunity_id) FILTER (WHERE closed_at IS NOT NULL),
         'opportunities', count(DISTINCT opportunity_id),
         'estimate_hours', CAST(COALESCE(sum(estimate_hours), 0) AS text),
         'actual_hours', CAST(COALESCE(sum(actual_hours), 0) AS text))
     FROM r) AS totals,
    (SELECT COALESCE(jsonb_object_agg(k.kind, k.n), '{}')
     FROM (SELECT assumption_kind AS kind, count(DISTINCT assumption_id) AS n
           FROM f WHERE assumption_kind IS NOT NULL GROUP BY assumption_kind) k) AS kinds,
    (SELECT count(DISTINCT assumption_id) FROM f) AS failed_total,
    (SELECT COALESCE(jsonb_agg(c.closed), '[]')
     FROM (SELECT count(DISTINCT r.opportunity_id) FILTER (WHERE r.closed_at IS NOT NULL)
                  AS closed
           FROM r CROSS JOIN LATERAL unnest(r.integration_type_ids) AS t(id)
           GROUP BY t.id) c) AS calibration,
    (SELECT COALESCE(jsonb_agg(to_jsonb(s)), '[]') FROM (
        SELECT group_key, max(group_label) AS group_label,
               CAST(opportunity_id AS text) AS opportunity_id,
               max(opportunity_title) AS title,
               CAST(estimate_version_id AS text) AS estimate_version_id,
               max(estimate_version) AS estimate_version, bool_or(is_baseline) AS is_baseline,
               variance_cause, count(*) AS n,
               CAST(sum(estimate_hours) AS text) AS estimate_hours,
               CAST(sum(actual_hours) AS text) AS actual_hours,
               CAST(sum(abs(actual_hours - estimate_hours)) AS text) AS abs_variance
        FROM g
        GROUP BY group_key, opportunity_id, estimate_version_id, variance_cause) s) AS stats,
    (SELECT COALESCE(jsonb_agg(to_jsonb(s)), '[]') FROM (
        SELECT g.group_key, CAST(g.opportunity_id AS text) AS opportunity_id,
               CAST(g.estimate_version_id AS text) AS estimate_version_id,
               GROUPING(g.opportunity_id) AS whole_group,
               count(DISTINCT f.assumption_id) AS n
        FROM g JOIN f ON f.actual_id = g.actual_id
        GROUP BY GROUPING SETS ((g.group_key),
                                (g.group_key, g.opportunity_id, g.estimate_version_id))
    ) s) AS failed
"""


def _report_statement(
    readable: opportunities.ReadableOpportunities, filters: ReportFilters, group_by: GroupBy
) -> sa.TextClause:
    readable_where = ["TRUE"]
    where = ["TRUE"]
    params: dict[str, Any] = {}
    types: list[sa.BindParameter[Any]] = []
    if not readable.everything:
        readable_where.append("v.opportunity_id = ANY(:opp_ids)")
        params["opp_ids"] = sorted(readable.ids, key=str)
        types.append(sa.bindparam("opp_ids", type_=postgresql.ARRAY(sa.Uuid())))
    if not filters.include_milestones:
        where.append("x.kind = 'final'")
    if filters.product is not None:
        where.append(
            "EXISTS (SELECT 1 FROM unnest(x.products) AS p WHERE lower(btrim(p)) = lower(:product))"
        )
        params["product"] = filters.product
    if filters.work_package_id is not None:
        where.append("x.work_package_id = :wp")
        params["wp"] = filters.work_package_id
        types.append(sa.bindparam("wp", type_=sa.Uuid()))
    if filters.cause is not None:
        where.append("x.variance_cause = :cause")
        params["cause"] = filters.cause.value
    if filters.closed_from is not None:
        where.append("CAST(x.closed_at AT TIME ZONE 'UTC' AS date) >= :closed_from")
        params["closed_from"] = filters.closed_from
        types.append(sa.bindparam("closed_from", type_=sa.Date()))
    if filters.closed_to is not None:
        where.append("CAST(x.closed_at AT TIME ZONE 'UTC' AS date) <= :closed_to")
        params["closed_to"] = filters.closed_to
        types.append(sa.bindparam("closed_to", type_=sa.Date()))
    ctes = f"""
WITH r_all AS MATERIALIZED (
    SELECT v.* FROM {VIEW} v WHERE {" AND ".join(readable_where)}
), r AS MATERIALIZED (
    SELECT x.* FROM r_all x WHERE {" AND ".join(where)}
), g AS MATERIALIZED (
    SELECT r.*, k.group_key, k.group_label
    FROM r CROSS JOIN LATERAL ({_GROUP_LATERAL[group_by]}) k
), f AS MATERIALIZED (
    SELECT fa.actual_id, fa.assumption_id, fa.assumption_kind
    FROM {FAILED_VIEW} fa WHERE fa.actual_id IN (SELECT actual_id FROM r)
)"""  # noqa: S608
    statement = sa.text(ctes + _REPORT_SELECT)
    if types:
        statement = statement.bindparams(*types)
    return statement.bindparams(**params) if params else statement


def _variance_view(estimate: Decimal, actual: Decimal) -> ReportVarianceView:
    rv = report_variance(estimate, actual)
    v = rv.variance
    return ReportVarianceView(
        hours=float(v.hours),
        percent=None if v.percent is None else float(v.percent),
        direction=v.direction,
        display=rv.display,
        sr_label=rv.sr_label,
        tone=rv.tone,
        bar_left=float(rv.bar.left),
        bar_width=float(rv.bar.width),
    )


# One frozen instance per cause, shared by every row that names it. A report on a few
# hundred Opportunities builds thousands of rows, and the fewer objects each request keeps
# alive, the less often a full garbage collection lands in it (Implementation Notes).
_CAUSE_REFS = {c: CauseRef(value=c, label=CAUSE_LABELS[c]) for c in VarianceCause}


def _cause_ref(cause: VarianceCause | None) -> CauseRef | None:
    return None if cause is None else _CAUSE_REFS[cause]


def _all_causes() -> list[CauseRef]:
    return list(_CAUSE_REFS.values())


@dataclass(slots=True)
class _OppAcc:
    opportunity_id: str
    version_id: str
    title: str
    version: int
    is_baseline: bool
    causes: list[CauseStats]
    estimate: Decimal = ZERO
    actual: Decimal = ZERO


@dataclass(slots=True)
class _GroupAcc:
    label: str | None
    causes: list[CauseStats]
    # By "{opportunity_id} {estimate_version_id}".
    opportunities: dict[str, _OppAcc]
    estimate: Decimal = ZERO
    actual: Decimal = ZERO


def _groups(report: sa.Row[Any], group_by: GroupBy) -> list[VarianceGroup]:
    group_failed: dict[str | None, int] = {}
    opp_failed: dict[tuple[str | None, str, str], int] = {}
    for f in report.failed:
        if f["whole_group"]:
            group_failed[f["group_key"]] = int(f["n"])
        else:
            opp_failed[(f["group_key"], f["opportunity_id"], f["estimate_version_id"])] = int(
                f["n"]
            )

    groups: dict[str | None, _GroupAcc] = {}
    for s in report.stats:
        estimate, actual = Decimal(s["estimate_hours"]), Decimal(s["actual_hours"])
        acc = groups.get(s["group_key"])
        if acc is None:
            acc = groups[s["group_key"]] = _GroupAcc(s["group_label"], [], {})
        acc.estimate += estimate
        acc.actual += actual
        opp_key = f"{s['opportunity_id']} {s['estimate_version_id']}"
        opp = acc.opportunities.get(opp_key)
        if opp is None:
            opp = acc.opportunities[opp_key] = _OppAcc(
                s["opportunity_id"],
                s["estimate_version_id"],
                s["title"],
                int(s["estimate_version"]),
                bool(s["is_baseline"]),
                [],
            )
        opp.estimate += estimate
        opp.actual += actual
        if s["variance_cause"] is not None:
            cause = CauseStats(
                VarianceCause(s["variance_cause"]), int(s["n"]), Decimal(s["abs_variance"])
            )
            acc.causes.append(cause)
            opp.causes.append(cause)

    result: list[VarianceGroup] = []
    for key, acc in groups.items():
        opps = [
            GroupOpportunity(
                opportunity_id=o.opportunity_id,
                title=o.title,
                estimate_version_id=o.version_id,
                estimate_version=o.version,
                is_baseline=o.is_baseline,
                estimate_hours=float(o.estimate),
                actual_hours=float(o.actual),
                variance=_variance_view(o.estimate, o.actual),
                main_cause=_cause_ref(main_cause(o.causes)),
                failed_assumptions=opp_failed.get((key, o.opportunity_id, o.version_id), 0),
            )
            for o in acc.opportunities.values()
        ]
        opps.sort(key=lambda o: (o.title.casefold(), o.opportunity_id, -o.estimate_version))
        result.append(
            VarianceGroup(
                key=NO_GROUP_KEY if key is None else key,
                label=_group_label(group_by, key, acc.label),
                opportunity_count=len({o.opportunity_id for o in opps}),
                estimate_hours=float(acc.estimate),
                actual_hours=float(acc.actual),
                variance=_variance_view(acc.estimate, acc.actual),
                main_cause=_cause_ref(main_cause(acc.causes)),
                failed_assumptions=group_failed.get(key, 0),
                opportunities=opps,
            )
        )
    # By label, ignoring case; the "No …" group last.
    result.sort(key=lambda g: (g.key == NO_GROUP_KEY, g.label.casefold(), g.key))
    return result


def _group_label(group_by: GroupBy, key: str | None, label: str | None) -> str:
    if key is None:
        return NO_GROUP_LABELS[group_by]
    if group_by == GroupBy.CAUSE:
        return CAUSE_LABELS[VarianceCause(key)]
    return label or key


def _kpis(report: sa.Row[Any]) -> VarianceKpis | None:
    totals = report.totals
    if int(totals["n"]) == 0:
        return None
    estimate, actual = Decimal(totals["estimate_hours"]), Decimal(totals["actual_hours"])
    by_kind = {str(k): int(n) for k, n in report.kinds.items()}
    return VarianceKpis(
        closed_opportunities=int(totals["closed"]),
        opportunities=int(totals["opportunities"]),
        estimate_hours=float(estimate),
        actual_hours=float(actual),
        variance=_variance_view(estimate, actual),
        failed_assumptions=int(report.failed_total),
        failed_by_kind=[
            FailedKindCount(
                kind=kind,
                label=labels[0] if by_kind.get(kind, 0) == 1 else labels[1],
                count=by_kind.get(kind, 0),
            )
            for kind, labels in FAILED_KIND_LABELS.items()
        ],
    )


def _options(report: sa.Row[Any]) -> ReportOptions:
    names: dict[str, str] = {}
    for name in sorted(report.products):
        names.setdefault(name.casefold(), name)
    return ReportOptions(
        products=sorted(names.values(), key=lambda n: (n.casefold(), n)),
        work_packages=sorted(
            (WorkPackageOption(id=p["id"], name=p["name"] or p["id"]) for p in report.packages),
            key=lambda p: (p.name.casefold(), p.id),
        ),
        causes=_all_causes(),
    )


def _empty_report(group_by: GroupBy, applied: AppliedFilters) -> EstimateVsActualReport:
    return EstimateVsActualReport(
        group_by=group_by,
        filters=applied,
        has_actuals=False,
        kpis=None,
        groups=[],
        calibration=Calibration(threshold=CALIBRATION_THRESHOLD, message=calibration_message([])),
        options=ReportOptions(products=[], work_packages=[], causes=_all_causes()),
    )


async def estimate_vs_actual(
    uow: UnitOfWork,
    actor: Principal,
    *,
    group_by: GroupBy = GroupBy.INTEGRATION_TYPE,
    filters: ReportFilters | None = None,
) -> EstimateVsActualReport:
    """Reports > Estimate vs actual (module docstring)."""
    authorize(actor, Action.REPORTING_REPORT_READ)
    filters = filters or ReportFilters()
    readable = await opportunities.readable_opportunities(uow, actor)
    applied = AppliedFilters(
        product=filters.product,
        work_package_id=None if filters.work_package_id is None else str(filters.work_package_id),
        cause=filters.cause,
        closed_from=filters.closed_from,
        closed_to=filters.closed_to,
        include_milestones=filters.include_milestones,
    )
    if not readable.everything and not readable.ids:
        return _empty_report(group_by, applied)
    statement = _report_statement(readable, filters, group_by)
    # The planner prices the view's per-row index lookups high, so a few thousand Actuals
    # cross `jit_above_cost` (and, later, the inlining and optimisation thresholds). JIT then
    # recompiles on every request, costing more than the query itself (~90 ms, over 1 s with
    # optimisation, against ~120 ms of execution), so it is off for this transaction only.
    await uow.session.execute(sa.text("SET LOCAL jit = off"))
    report = (await uow.session.execute(statement)).one()
    if not report.has_actuals:
        return _empty_report(group_by, applied)
    return EstimateVsActualReport(
        group_by=group_by,
        filters=applied,
        has_actuals=True,
        kpis=_kpis(report),
        groups=_groups(report, group_by),
        calibration=Calibration(
            threshold=CALIBRATION_THRESHOLD,
            message=calibration_message(int(c) for c in report.calibration),
        ),
        options=_options(report),
    )
