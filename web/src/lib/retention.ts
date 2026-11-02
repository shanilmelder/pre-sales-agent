// Admin → Retention (Story 10.6): display helpers. Read only: the API computes every retention
// date (never the browser) and only the daily purge job deletes. Safe on server and client.
import type { components } from "@/lib/api/client";

export type RetentionOverview = components["schemas"]["RetentionOverview"];
export type RetentionDue = components["schemas"]["RetentionDueItem"];
export type PurgeEvent = components["schemas"]["PurgeEventItem"];
export type RetentionRule = RetentionDue["rule"];

export const RETENTION_PERMISSION = "platform.retention.read";

export const DUE_HEADING = "Due for purge";
export const DUE_SUBLINE = "Retention date within the next 30 days, overdue ones included.";
export const RECENT_HEADING = "Recent purges";
export const RECENT_SUBLINE = "The last 20 purges, newest first.";
export const NO_DUE = "No Opportunity is due for purge in the next 30 days.";
export const NO_RECENT = "Nothing has been purged yet.";
export const RETENTION_FOOTNOTE =
  "Purged automatically each day after the retention date. Nothing can be deleted from here.";

/** The retention rule in words. */
export const RULE_LABELS: Record<RetentionRule, string> = {
  lost_3y: "Lost + 3 years",
  won_7y: "Won + 7 years",
};

/** Rows deleted in all, across modules. */
export function totalRows(event: PurgeEvent): number {
  return Object.values(event.rows_by_module).reduce((sum, rows) => sum + rows, 0);
}

/** "1 file" / "3 files". */
export function filesLabel(count: number): string {
  return `${count} ${count === 1 ? "file" : "files"}`;
}

/** "1 row" / "1,204 rows". */
export function rowsLabel(count: number): string {
  return `${count.toLocaleString("en-GB")} ${count === 1 ? "row" : "rows"}`;
}

/** The per-module counts as one line, e.g. "intake 12 · opportunities 2". */
export function rowsByModule(event: PurgeEvent): string {
  return Object.entries(event.rows_by_module)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([module, rows]) => `${module} ${rows.toLocaleString("en-GB")}`)
    .join(" · ");
}
