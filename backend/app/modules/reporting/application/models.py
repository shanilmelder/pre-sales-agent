"""Reports read models (Story 10.3). Hours and percents are floats to 0.1; every figure,
variance, colour tone and bar position comes from the server, never the browser."""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.reporting.domain.variance import Tone, VarianceCause, VarianceDirection


class GroupBy(StrEnum):
    INTEGRATION_TYPE = "integration_type"
    OPPORTUNITY = "opportunity"
    PRODUCT = "product"
    WORK_PACKAGE = "work_package"
    CAUSE = "cause"


NO_GROUP_KEY = "none"
"""The key of the group of rows with no value for the grouping (e.g. no Integration Type)."""


class ReportVarianceView(BaseModel):
    """Summed actual minus summed estimate: hours, percent (null when the estimate is 0), the
    direction, `display` (the signed percent, e.g. "+11.4%", or the signed hours "+12.0 h"
    with no estimate), `sr_label` ("over", "under" or "on estimate", read with the figure),
    `tone` (`over`: above +10 %, red; `under`: below -5 %, green; otherwise `neutral`) and the
    diverging bar's `bar_left` and `bar_width` (percents of the track, centred at 50)."""

    hours: float
    percent: float | None
    direction: VarianceDirection
    display: str
    sr_label: str
    tone: Tone
    bar_left: float
    bar_width: float


class CauseRef(BaseModel):
    # Frozen: one instance per cause is shared across a report's rows.
    model_config = ConfigDict(frozen=True)

    value: VarianceCause
    label: str


class FailedKindCount(BaseModel):
    kind: Literal["condition", "contingency"]
    label: str
    count: int


class VarianceKpis(BaseModel):
    """The KPI tiles: closed Opportunities (of the `opportunities` with Actuals in the
    report), the total variance over the report's distinct Actuals (each counted once, even
    when it is in several groups) with its estimate and actual totals, and the distinct failed
    Assumptions by kind."""

    closed_opportunities: int
    opportunities: int
    estimate_hours: float
    actual_hours: float
    variance: ReportVarianceView
    failed_assumptions: int
    failed_by_kind: list[FailedKindCount]


class GroupOpportunity(BaseModel):
    """One Opportunity's Actuals within a group, per Estimate Version they were recorded
    against (`estimate_version`, e.g. 3; `is_baseline`: it is the current Baseline)."""

    opportunity_id: str
    title: str
    estimate_version_id: str
    estimate_version: int
    is_baseline: bool
    estimate_hours: float
    actual_hours: float
    variance: ReportVarianceView
    main_cause: CauseRef | None
    failed_assumptions: int


class VarianceGroup(BaseModel):
    """One row of the table. `key` is the grouping value (an Integration Type, Opportunity or
    Work Package id, a product name or a cause), or `none` for rows without one."""

    key: str
    label: str
    opportunity_count: int
    estimate_hours: float
    actual_hours: float
    variance: ReportVarianceView
    main_cause: CauseRef | None
    failed_assumptions: int
    opportunities: list[GroupOpportunity]


class WorkPackageOption(BaseModel):
    id: str
    name: str


class ReportOptions(BaseModel):
    """The filter choices, from every readable Actual (filters ignored)."""

    products: list[str]
    work_packages: list[WorkPackageOption]
    causes: list[CauseRef]


class AppliedFilters(BaseModel):
    product: str | None
    work_package_id: str | None
    cause: VarianceCause | None
    closed_from: date | None
    closed_to: date | None
    include_milestones: bool


class Calibration(BaseModel):
    """The info strip: calibration isn't available yet; `message` says how many Integration
    Types have at least `threshold` closed Opportunities."""

    threshold: int
    message: str


class EstimateVsActualReport(BaseModel):
    """Reports > Estimate vs actual. `has_actuals` is false when the caller can read no
    Actual at all (the empty state); `kpis` is null when no Actual matches the filters."""

    group_by: GroupBy
    filters: AppliedFilters
    has_actuals: bool
    kpis: VarianceKpis | None
    groups: list[VarianceGroup]
    calibration: Calibration
    options: ReportOptions
