// Actuals display and entry helpers (Story 10.1). Safe on server and client. Variance, totals
// and percents always come from the server; nothing here computes them.
import type { components } from "@/lib/api/client";

export type ActualsView = components["schemas"]["ActualsView"];
export type ActualsLine = components["schemas"]["ActualsLine"];
export type ActualView = components["schemas"]["ActualView"];
export type ActualVersionView = components["schemas"]["ActualVersionView"];
export type ActualInput = components["schemas"]["ActualInput"];
export type ActualCorrection = components["schemas"]["ActualCorrection"];
export type VarianceView = components["schemas"]["VarianceView"];
export type VarianceCause = components["schemas"]["VarianceCause"];
export type ActualKind = components["schemas"]["ActualKind"];
export type CauseOption = components["schemas"]["CauseOption"];
export type AssumptionOption = components["schemas"]["AssumptionOption"];
export type SavedActuals = components["schemas"]["SavedActuals"];

/** One rule an Actual broke, as the API's 422 `actual_invalid` lists it. */
export type ActualError = { item: number | null; field: string; message: string };

export const ACTUALS_TITLE = "Actuals";
export const NO_BASELINE = "No Baseline yet. Actuals are recorded against the Baseline.";
export const EMPTY_TITLE = "No Actuals recorded";
export const EMPTY_BODY =
  "Record hours per Estimate line with a variance cause once delivery starts.";
export const RECORD_ACTUALS = "Record Actuals";
export const SAVE_ACTUALS = "Save Actuals";
export const IMPORT_FROM_FILE = "Import from file";
export const IMPORT_LATER = "Import arrives in a later release";
export const CLOSE_DELIVERY = "Close delivery";
export const CLOSE_WARNING =
  "This cannot be undone. Once delivery is closed, Actuals are locked and can no longer be recorded or corrected.";
export const FOOTNOTE =
  "Empty lines are not counted in variance. Each change is added to the Trace.";
export const NOT_RECORDED = "Not recorded";
export const STALE_LEAD = "Actuals changed since you opened them.";
export const REASON_LABEL = "Reason for the correction";
export const REASON_REQUIRED = "A reason is required to correct a recorded Actual.";
export const LOAD_FAILED = "The Actuals could not be loaded. Try again in a moment.";
export const SAVE_FAILED = "The Actuals could not be saved. Try again in a moment.";
export const ACTUALS_REASON_MAX = 1000;
export const DASH = "—";

/** The trace frames after which the Actuals tab is read again. */
export const ACTUALS_TRACE_EVENTS: readonly string[] = [
  "actuals.actual.recorded",
  "actuals.actual.corrected",
  "actuals.delivery.closed",
];

/** "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by
 * line." */
export function actualsSubtitle(version: number): string {
  return `Hours per Estimate line with a variance cause. Estimate v${version} · import from file or enter by line.`;
}

/** Hours to one decimal, tabular in the UI. */
export function hours(value: number): string {
  return value.toFixed(1);
}

/** The variance's colour: amber over, green under, secondary on estimate. Never red here, and
 * never colour alone (the label carries the sign and the words). */
export function varianceTone(variance: VarianceView | null): string {
  if (variance === null) return "text-text-secondary";
  if (variance.direction === "over") return "text-gap";
  if (variance.direction === "under") return "text-resolved";
  return "text-text-secondary";
}

export function causeLabel(value: VarianceCause | null, causes: readonly CauseOption[]): string {
  if (value === null) return DASH;
  return causes.find((c) => c.value === value)?.label ?? value;
}

export function kindLabel(kind: ActualKind): string {
  return kind === "final" ? "Final" : "Milestone";
}

export type SortOrder = "none" | "descending" | "ascending";

/** The next variance sort: none, largest overrun first, then smallest first. */
export function nextSort(order: SortOrder): SortOrder {
  return order === "none" ? "descending" : order === "descending" ? "ascending" : "none";
}

/** The lines in grid order, or by the server's variance hours (unrecorded lines last). */
export function sortLines(lines: readonly ActualsLine[], order: SortOrder): ActualsLine[] {
  if (order === "none") return [...lines];
  const sign = order === "descending" ? -1 : 1;
  return [...lines].sort((a, b) => {
    if (a.variance === null || b.variance === null) {
      return (a.variance === null ? 1 : 0) - (b.variance === null ? 1 : 0);
    }
    return sign * (a.variance.hours - b.variance.hours);
  });
}

/** Hours as typed: a number of 0 or more with at most one decimal place, null when blank,
 * "invalid" otherwise. */
export function parseHours(text: string): number | null | "invalid" {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (!/^\d{1,9}(\.\d)?$/.test(trimmed)) return "invalid";
  return Number(trimmed);
}

export const HOURS_RULE = "Enter hours of 0 or more, to one decimal place.";

/** What the person typed in a line's inline cells. */
export type LineDraft = { effort: string; cause: VarianceCause | "" };

export function draftOf(line: ActualsLine): LineDraft {
  return {
    effort: line.actual === null ? "" : hours(line.actual.effort_hours),
    cause: line.actual?.variance_cause ?? "",
  };
}

/** The fields an Actual keeps when only its hours or cause change inline. */
export function fieldsOf(actual: ActualView | ActualVersionView): Omit<ActualInput, "line_id" | "actual_id"> {
  return {
    kind: actual.kind,
    milestone_label: actual.milestone_label,
    effort_hours: actual.effort_hours,
    duration_days: actual.duration_days,
    cost_minor: actual.cost_minor,
    currency: actual.currency,
    variance_cause: actual.variance_cause,
    note: actual.note,
    failed_assumption_ids: actual.failed_assumptions.map((a) => a.assumption_id),
    integration_type_id: null,
    work_package_id: null,
  };
}

/** The entries Save Actuals sends: each line whose hours or cause differ from what is
 * recorded. A line without an Actual is recorded as final (milestones are entered in the
 * Inspector); a recorded one keeps its other fields. Lines with invalid hours are skipped
 * (`invalidLines` names them). */
export function changedItems(
  lines: readonly ActualsLine[],
  drafts: Readonly<Record<string, LineDraft>>,
): ActualInput[] {
  const items: ActualInput[] = [];
  for (const line of lines) {
    const draft = drafts[line.line_id];
    if (draft === undefined) continue;
    const effort = parseHours(draft.effort);
    if (effort === null || effort === "invalid") continue;
    const cause = draft.cause === "" ? null : draft.cause;
    const actual = line.actual;
    if (actual !== null && actual.effort_hours === effort && actual.variance_cause === cause) {
      continue;
    }
    items.push({
      ...(actual === null ? { kind: "final" as const } : fieldsOf(actual)),
      line_id: line.line_id,
      effort_hours: effort,
      variance_cause: cause,
    });
  }
  return items;
}

export const HOURS_NEEDED = "Enter hours to record this line";

/** The lines whose typed entry can't be saved: hours that aren't valid, or a cause chosen
 * with no hours (so Save never drops it silently). */
export function invalidLines(
  drafts: Readonly<Record<string, LineDraft>>,
): { lineId: string; message: string }[] {
  const found: { lineId: string; message: string }[] = [];
  for (const [lineId, draft] of Object.entries(drafts)) {
    const effort = parseHours(draft.effort);
    if (effort === "invalid") found.push({ lineId, message: HOURS_RULE });
    else if (effort === null && draft.cause !== "") found.push({ lineId, message: HOURS_NEEDED });
  }
  return found;
}

/** True when any entry corrects a recorded Actual, so Save Actuals asks for a reason once. */
export function needsReason(
  lines: readonly ActualsLine[],
  items: readonly ActualInput[],
): boolean {
  return items.some(
    (item) =>
      item.actual_id != null ||
      lines.some((line) => line.line_id === item.line_id && line.actual !== null),
  );
}

/** The API's field errors by line id (`item` indexes `items`), plus those for no line. */
export function errorsByLine(
  errors: readonly ActualError[],
  items: readonly ActualInput[],
): { byLine: Record<string, ActualError[]>; general: ActualError[] } {
  const byLine: Record<string, ActualError[]> = {};
  const general: ActualError[] = [];
  for (const error of errors) {
    const lineId = error.item === null ? null : (items[error.item]?.line_id ?? null);
    if (lineId === null) general.push(error);
    else (byLine[lineId] ??= []).push(error);
  }
  return { byLine, general };
}

/** True when the tab has no Actual at all (the empty-tab card). */
export function hasNoActuals(view: ActualsView): boolean {
  return (
    view.lines.every((line) => line.actual === null) &&
    view.unplanned.length === 0 &&
    view.version_mismatch === null
  );
}

/** The currency's minor-unit exponent (2 for EUR, 0 for JPY), from `Intl`; 2 when the code
 * isn't one `Intl` knows. */
export function currencyExponent(currency: string | null): number {
  if (currency === null || !/^[A-Za-z]{3}$/.test(currency)) return 2;
  try {
    return (
      new Intl.NumberFormat("en-GB", { style: "currency", currency: currency.toUpperCase() })
        .resolvedOptions().maximumFractionDigits ?? 2
    );
  } catch {
    return 2;
  }
}

/** A cost in minor units in its currency's own exponent: "EUR 4,800.00", "JPY 4,800". */
export function costText(costMinor: number | null, currency: string | null): string {
  if (costMinor === null || currency === null) return DASH;
  const digits = currencyExponent(currency);
  return `${currency} ${(costMinor / 10 ** digits).toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** An ISO timestamp as "27 Oct 2026" in the viewer's local time zone. */
export function formatLocalDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}
