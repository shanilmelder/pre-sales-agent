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
export type LineConflict = components["schemas"]["LineConflict"];
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
export const COLUMNS = ["Line", "Covers", "Role mix", "Effort h", "Cont. h", "Total h"] as const;

/** Hours as the grid shows them: one decimal place. */
export function hours(value: number): string {
  return value.toFixed(1);
}

/** "E 60 · PM 20 · QA 20". */
export function roleMixLabel(mix: RoleMix): string {
  return ROLES.map((role) => `${role.short} ${mix[role.value]}`).join(" · ");
}

/** "Draft", "Submitted" (Story 8.6) or "Superseded". */
export function versionStatusLabel(status: EstimateVersion["status"]): string {
  return status === "draft" ? "Draft" : status === "submitted" ? "Submitted" : "Superseded";
}

/** "Draft v2". */
export function versionLabel(
  version: Pick<EstimateVersion, "status" | "version">,
): string {
  return `${versionStatusLabel(version.status)} v${version.version}`;
}

/** The header's version pill: "Estimate v4 · from Assessments (run 3)" for a version built
 * from the specialist Assessments (Story 8.3), else "Draft v2". */
export function versionPillLabel(
  version: Pick<EstimateVersion, "status" | "version" | "source" | "source_run">,
): string {
  if (version.source !== "assessments") return versionLabel(version);
  const run = version.source_run == null ? "" : ` (run ${version.source_run})`;
  return `Estimate v${version.version} · from Assessments${run}`;
}

/** The toolbar's version pill: "v3 · Draft". */
export function versionTag(version: Pick<EstimateVersion, "status" | "version">): string {
  return `v${version.version} · ${versionStatusLabel(version.status)}`;
}

/** "From Assessments (run 2)", or null when the version names no run. */
export function fromRunLabel(version: Pick<EstimateVersion, "source_run">): string | null {
  return version.source_run == null ? null : `From Assessments (run ${version.source_run})`;
}

/** What a version was built from, in a sentence: "Assessments (run 2)", "Assessments" or
 * "a model draft". */
export function sourceLabel(version: Pick<EstimateVersion, "source" | "source_run">): string {
  if (version.source !== "assessments") return "a model draft";
  return version.source_run == null ? "Assessments" : `Assessments (run ${version.source_run})`;
}

export type LifecycleState = "passed" | "current" | "upcoming";

/** The Version lifecycle stepper: Draft → Baseline → Superseded, the version's status current,
 * Draft passed once submitted (Story 8.6: nothing is current until Baseline) or superseded.
 * The API has no Baseline status, so Baseline is never current or passed. */
export function lifecycleSteps(
  status: EstimateVersion["status"],
): { label: string; state: LifecycleState }[] {
  const labels = ["Draft", "Baseline", "Superseded"];
  if (status === "submitted")
    return labels.map((label, i) => ({ label, state: i === 0 ? "passed" : "upcoming" }));
  const at = status === "draft" ? 0 : 2;
  return labels.map((label, i) => ({
    label,
    state: i === at ? "current" : i === 0 && i < at ? "passed" : "upcoming",
  }));
}

/** The note under the stepper. */
export function versionNote(
  version: Pick<EstimateVersion, "status" | "version" | "source" | "source_run">,
): string {
  if (version.status === "submitted")
    return `v${version.version} was submitted and is read only.`;
  return version.status === "draft"
    ? `v${version.version} is a draft built from ${sourceLabel(version)}. Each edit needs a reason and is traced.`
    : `v${version.version} is superseded and read only.`;
}

/** "1 Requirement not covered by an Estimate line." */
export function uncoveredBanner(n: number): string {
  return `${requirementCount(n)} not covered by an Estimate line.`;
}

/** A role mix as bar segments: each role's share in percent of the whole (0 when empty). */
export function roleShares(
  mix: RoleMix,
): { value: RoleName; label: string; short: string; share: number; percent: number }[] {
  const sum = mixSum(mix);
  return ROLES.map((role) => ({
    ...role,
    share: mix[role.value],
    percent: sum > 0 ? (mix[role.value] / sum) * 100 : 0,
  }));
}

/** The grid footer's role hours: "Engineer 24.5 h · PM 8.2 h · QA 8.3 h" (QA only above 0). */
export function footerRoleLabel(totals: Pick<Totals, "role_hours">): string {
  return ROLES.filter((role) => role.value !== "qa" || totals.role_hours.qa > 0)
    .map((role) => {
      const name = role.value === "engineer" ? role.label : role.short;
      return `${name} ${hours(totals.role_hours[role.value])} h`;
    })
    .join(" · ");
}

/** The inspector's line heading: "Integration · line 2". */
export function lineHeading(line: Pick<EstimateLine, "section" | "position">): string {
  return `${sectionLabel(line.section)} · line ${line.position}`;
}

/** "1 Requirement", "3 Requirements". */
export function requirementCount(n: number): string {
  return `${n} ${n === 1 ? "Requirement" : "Requirements"}`;
}

/** The header while a draft is queued or running. */
export const DRAFTING = "Drafting Estimate";

/** The empty-state sentence (Story 8.3: the Estimate is built from the Assessments). */
export const NO_ESTIMATE =
  "No Estimate yet. Run assessment on the Assessments tab to build it.";

/** The empty-tab card's copy. */
export const NO_ESTIMATE_TITLE = "No Estimate yet";
export const NO_ESTIMATE_BODY =
  "Run Assessments to produce Estimate v1 from the confirmed Requirements.";
export const RUN_ASSESSMENT = "Run assessment";

/** The waiting state while an assessment run is queued or running and there is no version. */
export const BUILDING =
  "The Estimate is built when the Engineering, PM and Security Agents finish.";

/** The header note while an assessment run is queued or running and a version is shown. */
export const REBUILDING = "Rebuilding from the Assessments when the run finishes.";

/** Shown instead of the waiting indicator once polling has stopped (15 minutes). */
export const STILL_BUILDING = "Still waiting for the agents — reload to check.";

/** The marker on a line whose Requirement has an open Conflict (Story 8.3). */
export const OPEN_CONFLICT = "Open Conflict";

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
  registry_agent_disabled: "its agent is disabled",
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

/** The Register's summary pill: red "{n} not accepted block submit", else green "All accepted". */
export function registerStatus(counts: Pick<AssumptionCounts, "not_accepted">): {
  tone: "blocker" | "resolved";
  label: string;
} {
  return counts.not_accepted > 0
    ? { tone: "blocker", label: `${counts.not_accepted} not accepted block submit` }
    : { tone: "resolved", label: "All accepted" };
}

/** "Condition" or "Contingency". */
export function assumptionKindLabel(kind: AssumptionKind): string {
  return kind === "contingency" ? "Contingency" : "Condition";
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

/** "Accepted by Jane Doe · 5 Oct 2026". */
export function acceptedLabel(
  assumption: Pick<Assumption, "accepted_by" | "accepted_at">,
): string {
  const name = assumption.accepted_by?.name ?? "someone";
  return assumption.accepted_at
    ? `Accepted by ${name} · ${registerDate(assumption.accepted_at)}`
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
export function convertedLabel(kind: AssumptionKind | "risk" | null | undefined): string {
  if (kind === "risk") return "Converted to Risk";
  return kind === "contingency" ? "Converted to Contingency" : "Converted to Condition";
}

// --- Assumptions Register and Risks (Story 8.5) ---------------------------------------------

export type Risk = components["schemas"]["Risk"];
export type RiskLevel = components["schemas"]["RiskLevel"];

/** The register number: "A3". */
export function assumptionId(assumption: Pick<Assumption, "position">): string {
  return `A${assumption.position}`;
}

/** The Risks card number: "R2". */
export function riskId(risk: Pick<Risk, "position">): string {
  return `R${risk.position}`;
}

/** "Condition" or "Contingency · 8.0 h". */
export function assumptionLabel(
  assumption: Pick<Assumption, "kind" | "amount_hours">,
): string {
  const kind = assumptionKindLabel(assumption.kind);
  return assumption.amount_hours !== null && assumption.kind === "contingency"
    ? `${kind} · ${hours(assumption.amount_hours)} h`
    : kind;
}

/** The origin chip's text: "from Unknown: {title}" for an Unknown, else "from Gap: {title}". */
export function originLabel(item: {
  origin: { title: string };
  origin_is_unknown?: boolean;
}): string {
  return `from ${item.origin_is_unknown ? "Unknown" : "Gap"}: ${item.origin.title}`;
}

/** The origin chip's prefix ("from Gap: " / "from Unknown: "), shown before the title. */
export function originPrefix(item: { origin_is_unknown?: boolean }): string {
  return `from ${item.origin_is_unknown ? "Unknown" : "Gap"}: `;
}

/** A 404 on an Assumption or Risk edit. */
export const ITEM_GONE = "This item is no longer in the draft Estimate. Reload to see the latest.";

/** The text label beside a struck-through origin title (never colour alone). */
export const SUPERSEDED_ORIGIN = "superseded";

/** The Assumption inspector's edit hint. */
export const ASSUMPTION_EDIT_HINT = "Saving clears the acceptance. Recorded in the Decision Trace.";

/** The Risk inspector's edit hint. */
export const RISK_EDIT_HINT = "Recorded in the Decision Trace.";

/** Shown in place of the acceptance on an unaccepted Assumption. */
export const NOT_ACCEPTED_YET = "Not accepted";

/** In Unicode code points, on the trimmed text (the API's rule). */
export const WORDING_MAX = 500;
export const DESCRIPTION_MAX = 500;
export const CONTINGENCY_HOURS_MIN = 0.5;
export const CONTINGENCY_HOURS_MAX = 1000;
export const WORDING_RULE = "The wording must be 1 to 500 characters.";
export const CONTINGENCY_HOURS_RULE = "A Contingency needs 0.5 to 1,000 hours.";
export const DESCRIPTION_RULE = "The description must be 1 to 500 characters.";

/** A Contingency's hours as typed, if they round (half up, 0.1) into 0.5-1,000; else null. */
export function parseContingencyHours(raw: string): number | null {
  const value = parseEffort(raw);
  if (value === null) return null;
  const rounded = roundHours(value);
  return rounded >= CONTINGENCY_HOURS_MIN && rounded <= CONTINGENCY_HOURS_MAX ? value : null;
}

/** Risk levels, highest first, with their labels. */
export const RISK_LEVELS: readonly { value: RiskLevel; label: string }[] = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

/** "High", "Medium" or "Low". */
export function riskLevelLabel(level: RiskLevel): string {
  return RISK_LEVELS.find((l) => l.value === level)?.label ?? level;
}

/** The Risks card heading: "Risks · 2". */
export function risksHeading(n: number): string {
  return `Risks · ${n}`;
}

/** The Risks card's empty text. */
export const NO_RISKS = "No Risks yet. Convert a Gap to a Risk from the Gaps tab.";

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
