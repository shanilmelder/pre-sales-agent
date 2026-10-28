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
export type ActualsImportView = components["schemas"]["ActualsImportView"];
export type ImportRowView = components["schemas"]["ImportRowView"];
export type ActualsImportLatest = components["schemas"]["ActualsImportLatest"];
export type AppliedImport = components["schemas"]["AppliedImport"];
export type FailedAssumption = components["schemas"]["FailedAssumption"];

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
  "actuals.import.completed",
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

// --- the drill-down from Reports (Story 10.4) ----------------------------------------------

/** The Integration Type of the "No Integration Type" Reports group. */
export const NO_INTEGRATION_TYPE = "none";
export const NO_INTEGRATION_TYPE_LABEL = "No Integration Type";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What a Reports link carries to the Actuals tab: `sort=variance_desc|variance_asc` and
 * `integration_type={id}|none`. Anything else is ignored. */
export type ActualsDrill = { sort: SortOrder; integrationType: string | null };

type SearchParams = Record<string, string | string[] | undefined>;

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function parseActualsDrill(params: SearchParams | undefined): ActualsDrill {
  const sort = firstParam(params?.sort);
  const it = firstParam(params?.integration_type)?.trim();
  return {
    sort: sort === "variance_desc" ? "descending" : sort === "variance_asc" ? "ascending" : "none",
    integrationType:
      it && (it === NO_INTEGRATION_TYPE || UUID_PATTERN.test(it)) ? it.toLowerCase() : null,
  };
}

/** The lines tagged with the Integration Type (`none`: the lines with none); all of them
 * without a filter. Totals stay the server's. */
export function filterByIntegrationType(
  lines: readonly ActualsLine[],
  integrationType: string | null,
): ActualsLine[] {
  if (integrationType === null) return [...lines];
  if (integrationType === NO_INTEGRATION_TYPE) {
    return lines.filter((line) => line.integration_types.length === 0);
  }
  return lines.filter((line) =>
    line.integration_types.some((t) => t.id.toLowerCase() === integrationType),
  );
}

/** "Integration Type: SAP EWM" (the removable filter chip); "Integration Type: No Integration
 * Type" for `none`; "Integration Type: Unknown" when no line carries it. */
export function integrationTypeChipLabel(
  lines: readonly ActualsLine[],
  integrationType: string,
): string {
  if (integrationType === NO_INTEGRATION_TYPE) return `Integration Type: ${NO_INTEGRATION_TYPE_LABEL}`;
  const found = lines
    .flatMap((line) => line.integration_types)
    .find((t) => t.id.toLowerCase() === integrationType);
  return `Integration Type: ${found?.name ?? "Unknown"}`;
}

export const NO_LINES_FOR_TYPE = "No Baseline lines carry this Integration Type.";

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

// --- Import from file (Story 10.2) -----------------------------------------------------------

export const IMPORT_TITLE = "Import Actuals from a file";
export const IMPORT_INTRO =
  "Download the template, fill in Actual h and a variance cause per line, then choose the file. Nothing is saved until you confirm.";
export const DOWNLOAD_TEMPLATE = "Download template";
export const CHOOSE_FILE = "Choose file";
export const CONFIRM_IMPORT = "Confirm";
export const IMPORT_ACCEPT = ".xlsx,.csv";
export const IMPORT_HINT = ".xlsx or .csv, up to 5 MB";
export const PARSE_FAILED = "Parse failed";
export const RETRY = "Retry";
export const REPEAT_TICK = "Import it again";
export const EXCLUDE_INVALID = "Exclude invalid rows";
export const BATCH_REASON_LABEL = "Reason for the corrections";
export const IMPORT_STALE =
  "Actuals changed since the preview was read. The preview is refreshed: check it and confirm again.";
export const IMPORT_FAILED = "The import could not be applied. Try again in a moment.";
export const UPLOAD_FAILED = "The file could not be uploaded. Try again in a moment.";
export const TEMPLATE_FAILED = "The template could not be downloaded. Try again in a moment.";
export const IMPORT_FORBIDDEN = "Only delivery managers can import Actuals.";
export const REASON_ROW_MISSING = "correction reason missing";
export const NOT_IMPORTABLE =
  "Delivery is closed or there is no Baseline, so this file can't be imported.";
export const STILL_READING = "Still reading the file. Check again in a moment.";
export const CHECK_AGAIN = "Check again";
export const UNSAVED_EDITS = "Save or discard your changes first";

/** The import's status in the Sources pill's words: a running read shows as Parsing. */
export function importPillStatus(
  status: ActualsImportView["status"],
): "queued" | "parsing" | "parsed" | "failed" {
  if (status === "running") return "parsing";
  if (status === "applied") return "parsed";
  return status;
}

/** True while the worker is still reading the file (the dialog polls). */
export function isImportPending(view: ActualsImportView | null): boolean {
  return view !== null && (view.status === "queued" || view.status === "running");
}

/** The problems a row shows now: the server's, plus "correction reason missing" for a
 * correction with no reason of its own while no batch reason is typed. */
export function rowProblems(row: ImportRowView, batchReason: string): string[] {
  if (row.status === "correct" && row.reason_missing && batchReason.trim() === "") {
    return [...row.problems, `Row ${row.row}: ${REASON_ROW_MISSING}`];
  }
  return row.problems;
}

/** "3 to create · 1 to correct · 1 invalid · 2 skipped", for the rows not excluded. */
export function importSummary(
  rows: readonly ImportRowView[],
  excluded: ReadonlySet<number>,
  batchReason: string,
): string {
  let create = 0;
  let correct = 0;
  let invalid = 0;
  let skipped = 0;
  let left = 0;
  for (const row of rows) {
    if (row.status === "skipped") skipped += 1;
    else if (excluded.has(row.row)) left += 1;
    else if (rowProblems(row, batchReason).length > 0) invalid += 1;
    else if (row.status === "correct") correct += 1;
    else create += 1;
  }
  const parts = [`${create} to create`, `${correct} to correct`, `${invalid} invalid`];
  if (left > 0) parts.push(`${left} excluded`);
  if (skipped > 0) parts.push(`${skipped} skipped`);
  return parts.join(" · ");
}

/** Why Confirm can't go yet (null: it can): invalid rows not excluded, nothing to import, or
 * a repeated file without the tick. */
export function importBlocked(
  view: ActualsImportView,
  excluded: ReadonlySet<number>,
  batchReason: string,
  repeatTicked: boolean,
): string | null {
  if (view.status !== "parsed") return "The file hasn't been read yet.";
  if (view.estimate_version === null) return NOT_IMPORTABLE;
  const included = view.rows.filter((r) => r.status !== "skipped" && !excluded.has(r.row));
  const invalid = included.filter((r) => rowProblems(r, batchReason).length > 0).length;
  if (invalid === 1) return "1 row is invalid. Fix it in the file or exclude it.";
  if (invalid > 1) return `${invalid} rows are invalid. Fix them in the file or exclude them.`;
  if (included.length === 0) return "Nothing to import: every row is blank or excluded.";
  if (view.repeat_message !== null && !repeatTicked) {
    return `${view.repeat_message}. Tick “${REPEAT_TICK}” to import it once more.`;
  }
  return null;
}

/** The web route that downloads the Baseline version's import template. */
export function actualsTemplateUrl(opportunityId: string): string {
  return `/api/opportunities/${encodeURIComponent(opportunityId)}/actuals-template`;
}
