// Reports > Estimate vs actual (Story 10.3): types, URL parameters and labels. Safe on server
// and client. Every figure (variance, percent, tone, bar) comes from the API; the browser only
// formats and orders what it is given.
import type { components } from "@/lib/api/client";
import { isCalendarDate } from "@/app/opportunities/filters";
import { UUID_RE } from "@/lib/opportunities";

export type EstimateVsActualReport = components["schemas"]["EstimateVsActualReport"];
export type VarianceGroup = components["schemas"]["VarianceGroup"];
export type GroupOpportunity = components["schemas"]["GroupOpportunity"];
export type ReportVariance = components["schemas"]["ReportVarianceView"];
export type VarianceKpis = components["schemas"]["VarianceKpis"];
export type ReportOptions = components["schemas"]["ReportOptions"];
export type GroupBy = components["schemas"]["GroupBy"];
export type ReportCause = components["schemas"]["VarianceCause"];

export const REPORTS_HREF = "/reports";
export const PIPELINE_HREF = "/reports/pipeline";
export const COST_HREF = "/reports/cost";

/** The sub-tabs, in the mockup's order. */
export const REPORT_TABS = [
  { id: "variance", label: "Estimate vs actual", href: REPORTS_HREF },
  { id: "pipeline", label: "Pipeline", href: PIPELINE_HREF },
  { id: "cost", label: "Cost and usage", href: COST_HREF },
] as const;
export type ReportTab = (typeof REPORT_TABS)[number]["id"];

export const NOT_AVAILABLE_YET = "Not available yet.";
export const EMPTY_TITLE = "No Actuals recorded yet.";
export const EMPTY_BODY = "Delivery managers record them in an Opportunity's Actuals tab.";
export const NO_MATCH = "No Actuals match these filters.";
export const EXPORT_LATER = "Export arrives in a later release";
export const CALIBRATION_TITLE = "Calibration is not available yet.";

/** Group-by choices: the value, the select label and the table's first column. */
export const GROUP_BY: readonly { value: GroupBy; label: string }[] = [
  { value: "integration_type", label: "Integration Type" },
  { value: "opportunity", label: "Opportunity" },
  { value: "product", label: "Product" },
  { value: "work_package", label: "Work Package" },
  { value: "cause", label: "Cause" },
];
export const DEFAULT_GROUP_BY: GroupBy = "integration_type";

/** Every cause value (the record makes typecheck fail when the API adds or drops one). */
const CAUSE_SET = {
  unknown_requirement: true,
  integration_complexity: true,
  customer_delay: true,
  scope_change: true,
  estimation_error: true,
  other: true,
} satisfies Record<ReportCause, true>;
const CAUSES = Object.keys(CAUSE_SET) as ReportCause[];

export function groupByLabel(groupBy: GroupBy): string {
  return GROUP_BY.find((g) => g.value === groupBy)?.label ?? "Integration Type";
}

/** The report's parameters as kept in the URL. Defaults are left out. */
export type ReportParams = {
  groupBy: GroupBy;
  product?: string;
  workPackageId?: string;
  cause?: ReportCause;
  closedFrom?: string;
  closedTo?: string;
  includeMilestones: boolean;
};

type SearchParams = Record<string, string | string[] | undefined> | URLSearchParams;

function first(params: SearchParams | undefined, key: string): string | undefined {
  if (!params) return undefined;
  if (params instanceof URLSearchParams) return params.get(key) ?? undefined;
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

/** The parameters in `params`. Invalid values are dropped, so a hand-edited URL never gets a
 * 422 from the API; a reversed date range drops both dates. */
export function parseReportParams(params: SearchParams | undefined): ReportParams {
  const groupBy = first(params, "group_by");
  const result: ReportParams = {
    groupBy: GROUP_BY.some((g) => g.value === groupBy) ? (groupBy as GroupBy) : DEFAULT_GROUP_BY,
    includeMilestones: first(params, "include_milestones") === "true",
  };
  const product = first(params, "product")?.trim();
  if (product && Array.from(product).length <= 100) result.product = product;
  const wp = first(params, "work_package_id");
  if (wp && UUID_RE.test(wp)) result.workPackageId = wp.toLowerCase();
  const cause = first(params, "cause");
  if (cause && (CAUSES as readonly string[]).includes(cause)) result.cause = cause as ReportCause;
  const from = first(params, "closed_from");
  const to = first(params, "closed_to");
  const validFrom = from && isCalendarDate(from) ? from : undefined;
  const validTo = to && isCalendarDate(to) ? to : undefined;
  if (!(validFrom && validTo && validFrom > validTo)) {
    if (validFrom) result.closedFrom = validFrom;
    if (validTo) result.closedTo = validTo;
  }
  return result;
}

/** The API's query for `params`. */
export function reportQuery(params: ReportParams) {
  return {
    group_by: params.groupBy,
    product: params.product,
    work_package_id: params.workPackageId,
    cause: params.cause,
    closed_from: params.closedFrom,
    closed_to: params.closedTo,
    include_milestones: params.includeMilestones,
  };
}

/** `/reports?…` for `params`, leaving defaults out. */
export function reportHref(params: ReportParams): string {
  const query = new URLSearchParams();
  if (params.groupBy !== DEFAULT_GROUP_BY) query.set("group_by", params.groupBy);
  if (params.product) query.set("product", params.product);
  if (params.workPackageId) query.set("work_package_id", params.workPackageId);
  if (params.cause) query.set("cause", params.cause);
  if (params.closedFrom) query.set("closed_from", params.closedFrom);
  if (params.closedTo) query.set("closed_to", params.closedTo);
  if (params.includeMilestones) query.set("include_milestones", "true");
  const text = query.toString();
  return text ? `${REPORTS_HREF}?${text}` : REPORTS_HREF;
}

const HOURS = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const WHOLE_HOURS = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });

/** "468.0" (table cells). */
export function formatHours(hours: number): string {
  return HOURS.format(hours);
}

/** "1,126 h" (KPI sublines). */
export function formatWholeHours(hours: number): string {
  return `${WHOLE_HOURS.format(hours)} h`;
}

export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** A group's muted subline: "3 Opportunities · 2 failed Assumptions". */
export function groupSubline(group: VarianceGroup): string {
  return `${plural(group.opportunity_count, "Opportunity", "Opportunities")} · ${plural(
    group.failed_assumptions,
    "failed Assumption",
    "failed Assumptions",
  )}`;
}

/** The variance figure's colour (the API's tone): red above +10 %, green below −5 %. */
export function toneClass(variance: ReportVariance): string {
  if (variance.tone === "over") return "text-blocker";
  if (variance.tone === "under") return "text-resolved";
  return "text-text-secondary";
}

export function barClass(variance: ReportVariance): string {
  if (variance.tone === "over") return "bg-blocker";
  if (variance.tone === "under") return "bg-resolved";
  return "bg-text-secondary";
}

export type SortKey = "label" | "estimate" | "actual" | "variance";
export type SortState = { key: SortKey; order: "ascending" | "descending" } | null;

/** The next sort after clicking `key`'s header: descending, ascending, then the server's order
 * (names start ascending). */
export function nextSort(state: SortState, key: SortKey): SortState {
  const firstOrder = key === "label" ? "ascending" : "descending";
  if (!state || state.key !== key) return { key, order: firstOrder };
  if (state.order === firstOrder) {
    return { key, order: firstOrder === "ascending" ? "descending" : "ascending" };
  }
  return null;
}

/** Variance sorts by percent (the bar), groups with no estimate by hours after them. */
function sortValue(group: VarianceGroup, key: Exclude<SortKey, "label">): number {
  if (key === "estimate") return group.estimate_hours;
  if (key === "actual") return group.actual_hours;
  return group.variance.percent ?? group.variance.hours;
}

/** The groups in `state`'s order (a copy); null keeps the server's order. */
export function sortGroups(groups: readonly VarianceGroup[], state: SortState): VarianceGroup[] {
  if (!state) return [...groups];
  const sign = state.order === "ascending" ? 1 : -1;
  return [...groups].sort((a, b) => {
    if (state.key === "label") return sign * a.label.localeCompare(b.label, "en", { sensitivity: "base" });
    return sign * (sortValue(a, state.key) - sortValue(b, state.key));
  });
}

export function ariaSort(state: SortState, key: SortKey): "ascending" | "descending" | "none" {
  return state && state.key === key ? state.order : "none";
}
