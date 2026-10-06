// Estimate display helpers (Story 8.1 + 8.2, demo scope). Safe on server and client. Every
// number comes from the server; nothing here adds hours up.
import type { components } from "@/lib/api/client";

export type EstimateView = components["schemas"]["EstimateView"];
export type EstimateVersion = components["schemas"]["EstimateVersion"];
export type EstimateSection = components["schemas"]["EstimateSection"];
export type EstimateLine = components["schemas"]["EstimateLine"];
export type EstimateDraft = components["schemas"]["EstimateDraft"];
export type DraftErrorCode = components["schemas"]["DraftErrorCode"];
export type LineRequirement = components["schemas"]["LineRequirement"];
export type Totals = components["schemas"]["Totals"];
export type RoleHours = components["schemas"]["RoleHours"];
export type RoleMix = components["schemas"]["RoleMix"];
export type SectionName = components["schemas"]["Section"];
export type RoleName = components["schemas"]["EstimateRole"];

/** The template's sections with their labels, in template order. */
export const SECTIONS: readonly { value: SectionName; label: string }[] = [
  { value: "functional", label: "Functional" },
  { value: "integration", label: "Integration" },
  { value: "data", label: "Data" },
  { value: "security", label: "Security" },
  { value: "non_functional", label: "Non-functional" },
  { value: "commercial", label: "Commercial" },
];

export function sectionLabel(value: SectionName): string {
  return SECTIONS.find((s) => s.value === value)?.label ?? value;
}

/** The template's roles with their full and short labels, in column order. */
export const ROLES: readonly {
  value: RoleName;
  label: string;
  short: string;
}[] = [
  { value: "engineer", label: "Engineer", short: "E" },
  { value: "project_manager", label: "Project manager", short: "PM" },
  { value: "qa", label: "QA", short: "QA" },
];

/** The grid's columns (template `demo-1`). */
export const COLUMNS = [
  "Line",
  "Covers",
  "Role mix (%)",
  "Effort (h)",
  "Contingency (h)",
  "Total (h)",
] as const;

/** Hours as the grid shows them: one decimal place. */
export function hours(value: number): string {
  return value.toFixed(1);
}

/** "E 60 · PM 20 · QA 20". */
export function roleMixLabel(mix: RoleMix): string {
  return ROLES.map((role) => `${role.short} ${mix[role.value]}`).join(" · ");
}

/** "Draft" or "Superseded". */
export function versionStatusLabel(status: EstimateVersion["status"]): string {
  return status === "draft" ? "Draft" : "Superseded";
}

/** "Draft v2". */
export function versionLabel(
  version: Pick<EstimateVersion, "status" | "version">,
): string {
  return `${versionStatusLabel(version.status)} v${version.version}`;
}

/** "1 Requirement", "3 Requirements". */
export function requirementCount(n: number): string {
  return `${n} ${n === 1 ? "Requirement" : "Requirements"}`;
}

/** "1 Requirement not covered", "2 Requirements not covered". */
export function uncoveredLabel(n: number): string {
  return `${requirementCount(n)} not covered`;
}

/** The header while a draft is queued or running. */
export const DRAFTING = "Drafting Estimate";

/** The empty-state sentence. */
export const NO_ESTIMATE = "The Estimate is drafted after Gaps are detected.";

/** A finished draft that stored no version (no active Requirements). */
export const NOTHING_TO_ESTIMATE =
  "There were no active Requirements to estimate.";

/** Shown instead of the running indicator once polling has stopped (15 minutes). */
export const STILL_DRAFTING = "Still drafting — reload to check.";

/** Why a draft failed, as the Estimate tab says it. */
export const DRAFT_FAILURE_REASONS: Record<DraftErrorCode, string> = {
  model_unavailable: "the model service couldn't be reached",
  model_timeout: "the model took too long to answer",
  output_invalid: "the model's answer couldn't be used",
};

/** "Estimate draft failed: <reason>" (a general reason for a code this build doesn't know). */
export function draftFailure(code: DraftErrorCode | null | undefined): string {
  const reason =
    (code ? DRAFT_FAILURE_REASONS[code] : undefined) ?? "something went wrong";
  return `Estimate draft failed: ${reason}`;
}

/** True while the draft is queued or running. */
export function isDrafting(draft: EstimateDraft | null | undefined): boolean {
  return draft?.status === "queued" || draft?.status === "running";
}

/** How often the Estimate tab re-reads the Estimate while drafting. */
export const DRAFT_POLL_MS = 2000;

/** Polling stops after this long of continuous drafting (a reload resumes it). */
export const DRAFT_POLL_LIMIT_MS = 15 * 60 * 1000;

// --- editing a line (Story 8.2, demo scope) ------------------------------------------------

/** The longest reason the API accepts, in characters (trimmed). */
export const REASON_MAX = 300;
export const EFFORT_MAX = 2000;

/** The local check on a typed effort (the API decides; this only avoids a useless call). */
export const EFFORT_RULE = "Effort must be a number of hours from 0 to 2,000.";
export const MIX_RULE = "Role mix must name every role and add up to 100%.";
export const REASON_LABEL = "Reason for the change";
export const EDIT_SAVE_FAILED = "The change could not be saved. Try again.";
export const EDIT_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can edit the Estimate.";
export const VERSION_REPLACED =
  "This Estimate Version was replaced by a newer draft. Reload to see it.";

/** The typed effort as hours, or null when it isn't a number from 0 to 2,000. */
export function parseEffort(raw: string): number | null {
  let text = raw.trim();
  // Commas only as thousands separators ("1,000", "1,500.5"); any other comma is refused.
  if (text.includes(",")) {
    if (!/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(text)) return null;
    text = text.replaceAll(",", "");
  }
  if (!/^\d+(\.\d+)?$|^\.\d+$/.test(text)) return null;
  const value = Number(text);
  // The server rounds half up to 0.1 before its 0-2,000 check: so does this one.
  return Number.isFinite(value) && roundHours(value) <= EFFORT_MAX ? value : null;
}

/** Hours rounded half up to 0.1, as the server stores them (0.35 -> 0.4). */
export function roundHours(value: number): number {
  return Math.round(Number((value * 10).toPrecision(12))) / 10;
}

/** Hours as the server will store them, with one decimal place: "0.4" for 0.35. */
export function roundedHours(value: number): string {
  return hours(roundHours(value));
}

/** The sum of a role mix's shares. */
export function mixSum(mix: RoleMix): number {
  return ROLES.reduce((sum, role) => sum + mix[role.value], 0);
}

/** "Edited", or "Edited, carried from v1" for an edit a re-draft carried; null when the line
 * was never edited. */
export function editedLabel(
  line: Pick<EstimateLine, "edited" | "edit_carried_from_version">,
): string | null {
  if (!line.edited) return null;
  return line.edit_carried_from_version == null
    ? "Edited"
    : `Edited, carried from v${line.edit_carried_from_version}`;
}

/** "Jane Doe, 5 Oct 2026: Reuse the existing connector" (null when never edited). */
export function editHistory(
  line: Pick<EstimateLine, "edited" | "edited_by_name" | "edited_at" | "edit_reason">,
): string | null {
  if (!line.edited) return null;
  const name = line.edited_by_name ?? "someone";
  const when = line.edited_at ? `, ${registerDate(line.edited_at)}` : "";
  return `${name}${when}: ${line.edit_reason ?? ""}`;
}

/** "1 edited line from v2 had no matching line; it stays in v2 and the Trace." */
export function uncarriedEditsNote(count: number, from: number | null | undefined): string {
  const v = from == null ? "the previous version" : `v${from}`;
  return count === 1
    ? `1 edited line from ${v} had no matching line; it stays in ${v} and the Trace.`
    : `${count} edited lines from ${v} had no matching line; they stay in ${v} and the Trace.`;
}

/** Where the browser keeps the user's last reason on an Opportunity's Estimate: one key per
 * Opportunity, holding `{versionId, reason}` (a convenience only). */
export function reasonStorageKey(opportunityId: string): string {
  return `psa.estimate.reason.${opportunityId}`;
}

/** The kept reason, if it was given on `versionId`; "" otherwise (or when unreadable). */
export function readKeptReason(opportunityId: string, versionId: string): string {
  try {
    const raw = window.localStorage.getItem(reasonStorageKey(opportunityId));
    const kept = raw ? (JSON.parse(raw) as { versionId?: unknown; reason?: unknown }) : null;
    return kept?.versionId === versionId && typeof kept.reason === "string" ? kept.reason : "";
  } catch {
    return "";
  }
}

/** Keep the last reason for `versionId`, replacing any earlier version's. */
export function keepReason(opportunityId: string, versionId: string, reason: string): void {
  try {
    window.localStorage.setItem(
      reasonStorageKey(opportunityId),
      JSON.stringify({ versionId, reason }),
    );
  } catch {
    // A convenience only.
  }
}

/** Shown when a new Estimate version replaced the lines an open editor was changing. */
export const NEW_VERSION_ARRIVED = "A new Estimate version arrived; your change was not saved.";

// --- Assumptions Register (Story 8.4 + 8.5, demo scope) ------------------------------------

export type Assumption = components["schemas"]["Assumption"];
export type AssumptionKind = components["schemas"]["AssumptionKind"];
export type AssumptionCounts = components["schemas"]["AssumptionCounts"];
export type OriginGap = components["schemas"]["OriginGap"];
export type UnconvertedGap = components["schemas"]["UnconvertedGap"];
export type ProposalStatus = components["schemas"]["ProposalStatus"];

/** The grid's version-level row for Contingencies linked to no line. */
export const UNALLOCATED_CONTINGENCY = "Unallocated contingency";

/** The Register's group headings. */
export const CONDITIONS = "Conditions";
export const CONTINGENCIES = "Contingencies";

/** The label of an unaccepted (blocker) row: never colour alone. */
export const NOT_ACCEPTED = "Not accepted";

/** Shown while the Assumption proposals are queued or running. */
export const PROPOSING = "Proposing Assumptions";

/** Shown when the Assumption proposals failed. */
export const PROPOSALS_FAILED = "Assumptions couldn't be proposed.";

/** Shown for a draft version made before Assumptions were proposed. */
export const PROPOSALS_MISSING = "No Assumptions were proposed for this version.";

/** The "Unconverted Gaps" note's heading. */
export const UNCONVERTED_GAPS = "Unconverted Gaps";

/** True while the version's Assumption proposals are queued or running. */
export function isProposing(
  version: Pick<EstimateVersion, "proposal_status"> | null | undefined,
) {
  return (
    version?.proposal_status === "queued" ||
    version?.proposal_status === "running"
  );
}

/** The Register header: "7 · 6 accepted · 1 not accepted". */
export function registerSummary(counts: AssumptionCounts): string {
  return `${counts.total} · ${counts.accepted} accepted · ${counts.not_accepted} not accepted`;
}

/** "Accept all (3)". */
export function acceptAllLabel(n: number): string {
  return `Accept all (${n})`;
}

/** A date as the Register shows it, e.g. "5 Oct 2026" (UTC, so server and client agree). */
export function registerDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(iso));
}

/** "Accepted by Jane Doe, 5 Oct 2026". */
export function acceptedLabel(
  assumption: Pick<Assumption, "accepted_by" | "accepted_at">,
): string {
  const name = assumption.accepted_by?.name ?? "someone";
  return assumption.accepted_at
    ? `Accepted by ${name}, ${registerDate(assumption.accepted_at)}`
    : `Accepted by ${name}`;
}

/** "Carried from v1" for an Assumption a re-draft carried forward; null for a proposal. */
export function carriedLabel(assumption: Pick<Assumption, "carried_from_version">): string | null {
  return assumption.carried_from_version == null
    ? null
    : `Carried from v${assumption.carried_from_version}`;
}

/** "Changed by Jane Doe since you opened it." (someone else when unknown). */
export function staleMessage(changedBy: string | null | undefined): string {
  return `Changed by ${changedBy ?? "someone else"} since you opened it.`;
}

/** A converted Gap's label on the Gaps tab. */
export function convertedLabel(
  kind: AssumptionKind | null | undefined,
): string {
  return kind === "contingency"
    ? "Converted to Contingency"
    : "Converted to Condition";
}

// --- Export (Story 8.8, demo scope) ---------------------------------------------------------

export type ExportFormat = components["schemas"]["ExportFormat"];

/** The Export control's choices, in menu order. */
export const EXPORT_FORMATS: readonly { value: ExportFormat; label: string }[] = [
  { value: "xlsx", label: "Excel (.xlsx)" },
  { value: "docx", label: "Word (.docx)" },
];

export const EXPORT = "Export";
export const EXPORTING = "Exporting…";

/** The web route that downloads the export (it adds the user's token). */
export function exportUrl(opportunityId: string, format: ExportFormat): string {
  return `/api/opportunities/${encodeURIComponent(opportunityId)}/estimate-export?format=${format}`;
}

/** The file name from `Content-Disposition: attachment; filename="…"`, or null. */
export function exportFileName(disposition: string | null | undefined): string | null {
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  return match ? match[1] : null;
}

/** Why an export failed, by HTTP status and problem code. */
export function exportFailureReason(status: number | null, code?: string | null): string {
  if (status === null || status === 502) return "the export service couldn't be reached";
  if (status === 401) return "your session has expired; reload the page";
  if (status === 403) {
    return "only the owner and collaborators, except sales representatives, can export the Estimate";
  }
  if (status === 404) return "you no longer have access to this Opportunity";
  if (status === 409 || code === "estimate_not_found") return "there is no Estimate to export yet";
  return "the file couldn't be created";
}

/** "Export failed: <reason>". */
export function exportFailure(reason: string): string {
  return `Export failed: ${reason}`;
}
