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
export type BaselineRef = components["schemas"]["BaselineRef"];
export type VersionListItem = components["schemas"]["VersionListItem"];
export type VersionGate = components["schemas"]["VersionGate"];
export type BaselineApproval = components["schemas"]["BaselineApproval"];
export type BaselineSet = components["schemas"]["BaselineSet"];

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

const VERSION_STATUS_LABELS: Record<EstimateVersion["status"], string> = {
  draft: "Draft",
  submitted: "Submitted",
  in_review: "In review",
  approved: "Approved",
  rejected: "Rejected",
  superseded: "Superseded",
};

/** "Draft", "Submitted" (Story 8.6), "In review" (Story 9.1), "Approved", "Rejected" (Story
 * 9.3) or "Superseded". */
export function versionStatusLabel(status: EstimateVersion["status"]): string {
  return VERSION_STATUS_LABELS[status] ?? status;
}

/** Whether the version was submitted (and so is read only): `submitted`, `in_review`, or
 * reviewed (`approved`, `rejected`). */
export function isSent(status: EstimateVersion["status"]): boolean {
  return (
    status === "submitted" ||
    status === "in_review" ||
    status === "approved" ||
    status === "rejected"
  );
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

/** The Version lifecycle stepper (the mockup's four steps): Draft → In review → Approved →
 * Baseline. Draft is current for a draft and passed once the version is submitted or
 * superseded (the version pill says Superseded); In review is current while a Review Request
 * is pending (Story 9.1); Approved is current, with In review passed, once every Review
 * Request is approved (Story 9.3). Story 9.7: every step is passed for the Baseline. */
export function lifecycleSteps(
  status: EstimateVersion["status"],
  isBaseline = false,
): { label: string; state: LifecycleState }[] {
  const labels = ["Draft", "In review", "Approved", "Baseline"];
  if (isBaseline) return labels.map((label) => ({ label, state: "passed" }));
  const current = ["draft", "in_review", "approved"].indexOf(status);
  return labels.map((label, i) => ({
    label,
    state:
      i === current ? "current" : i === 0 || (current > 0 && i < current) ? "passed" : "upcoming",
  }));
}

/** The note under the stepper. */
export function versionNote(
  version: Pick<EstimateVersion, "status" | "version" | "source" | "source_run">,
  isBaseline = false,
): string {
  if (isBaseline) return baselineNote(version.version);
  if (version.status === "submitted")
    return `v${version.version} was submitted and is read only.`;
  if (version.status === "in_review")
    return `v${version.version} is in review and read only.`;
  if (version.status === "approved")
    return `v${version.version} is approved by every reviewer and read only.`;
  if (version.status === "rejected")
    return `v${version.version} was rejected in review and is read only.`;
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

// --- the Baseline and the version switcher (Story 9.7) --------------------------------------

export const BASELINE = "Baseline";
export const SET_BASELINE = "Set Baseline";
export const ALL_VERSIONS = "All versions";

/** "v2 is the Baseline. …" (the stepper's note on the Baseline version). */
export function baselineNote(version: number): string {
  return (
    `v${version} is the Baseline. A Baseline is replaced only by a newer approved version, ` +
    "and editing it creates a new version."
  );
}

/** "Baseline v3" (the Opportunities list's estimate cell). */
export function baselineTag(version: number): string {
  return `Baseline v${version}`;
}

/** Whether `version` is the Opportunity's current Baseline. */
export function isBaselineVersion(
  view: Pick<EstimateView, "baseline">,
  version: Pick<EstimateVersion, "id"> | null | undefined,
): boolean {
  return Boolean(version && view.baseline && view.baseline.version_id === version.id);
}

/** The switcher's segments: the Baseline (if any), then the two most recent versions, without
 * repeating one, and the selected version (`selected`, its number) when it is none of them. */
export function switcherVersions(
  versions: readonly VersionListItem[],
  selected?: number | null,
): VersionListItem[] {
  const baseline = versions.find((v) => v.is_baseline);
  const newest = [...versions].sort((a, b) => b.version - a.version).slice(0, 2);
  const picked = baseline ? [baseline, ...newest.filter((v) => v.id !== baseline.id)] : newest;
  const chosen = versions.find((v) => v.version === selected);
  return chosen && !picked.includes(chosen) ? [...picked, chosen] : picked;
}

/** The Estimate tab's href for one version: `?version=n` (none for the current one). */
export function versionHref(opportunityId: string, version: number | null): string {
  const base = `/opportunities/${opportunityId}/estimate`;
  return version === null ? base : `${base}?version=${version}`;
}

/** `?version=n` as a positive whole number, or null. */
export function parseVersionParam(value: string | string[] | undefined | null): number | null {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^[1-9][0-9]{0,8}$/.test(raw)) return null;
  return Number(raw);
}

/** "Estimate v3 is now the Baseline" (announced after Set Baseline). */
export function baselineSetAnnouncement(version: number): string {
  return `Estimate v${version} is now the Baseline`;
}

/** "Set Baseline for Estimate v3?". */
export function setBaselineTitle(version: number): string {
  return `Set Baseline for Estimate v${version}?`;
}

/** "v3 is superseded and can't become the Baseline." */
export function supersededReason(version: number): string {
  return `v${version} is superseded and can't become the Baseline.`;
}

/** "v3 was rejected in review." */
export function rejectedReason(version: number): string {
  return `v${version} was rejected in review.`;
}

/** "Every requested review must approve v3 first." */
export function approveFirstReason(version: number): string {
  return `Every requested review must approve v${version} first.`;
}

export const BASELINE_WARNING =
  "This cannot be undone. A Baseline is replaced only by a newer approved version.";
export const BASELINE_STALE = "Changed since you opened it.";
export const BASELINE_FAILED = "Not set: the platform is not reachable. Try again.";
export const BASELINE_FORBIDDEN = "You can't set the Baseline of this Estimate.";
export const APPROVERS_FAILED = "The approvers could not be loaded.";
export const NO_APPROVERS = "No approvals recorded.";

const LONG_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** "Approved 21 Oct 2026" (the dialog's approver pill). */
export function approvedOn(decidedAt: string | null | undefined): string {
  const date = decidedAt ? new Date(decidedAt) : null;
  return date && !Number.isNaN(date.getTime())
    ? `Approved ${LONG_DATE.format(date)}`
    : "Approved";
}

/** "21 Oct 2026" (the All versions list). */
export function longDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : LONG_DATE.format(date);
}

// --- lineage and compare (Story 9.9) --------------------------------------------------------

export type LineLineage = components["schemas"]["LineLineage"];
export type LineageRequirement = components["schemas"]["LineageRequirement"];
export type LineageFinding = components["schemas"]["LineageFinding"];
export type LineageDecision = components["schemas"]["LineageDecision"];
export type LineageAssumption = components["schemas"]["LineageAssumption"];
export type LineageEdit = components["schemas"]["LineageEdit"];
export type LineageReview = components["schemas"]["LineageReview"];
export type LineageEvidence = components["schemas"]["LineageEvidence"];
export type LineageActor = components["schemas"]["LineageActor"];
export type AssumptionLineage = components["schemas"]["AssumptionLineage"];
export type LineageStep = components["schemas"]["LineageStep"];
export type VersionComparison = components["schemas"]["VersionComparison"];
export type LineDiff = components["schemas"]["LineDiff"];
export type ItemDiff = components["schemas"]["ItemDiff"];
export type WhyEvent = components["schemas"]["WhyEvent"];

export const LINEAGE = "Lineage";
export const TRACE = "Trace";
export const OPEN_IN_TRACE = "Open in Trace";
export const NOTHING_RECORDED = "Nothing recorded.";
export const LINEAGE_FAILED = "The lineage could not be loaded.";
export const LOADING_LINEAGE = "Loading lineage";
export const SUPERSEDED = "superseded";
export const WHY_IT_CHANGED = "Why it changed";
export const COMPARE_FAILED = "The comparison could not be loaded.";
export const LOADING_COMPARISON = "Loading comparison";
export const NO_CHANGE = "no change";
export const NO_ITEM_CHANGES = "No Assumption or Risk changes.";
export const NO_WHY_EVENTS = "No recorded decisions between these versions.";

/** The line's lineage sections, in order, with their headings. */
export const LINE_LINEAGE_SECTIONS = [
  { key: "requirements", label: "Requirements" },
  { key: "findings", label: "Findings" },
  { key: "decisions", label: "Decisions" },
  { key: "assumptions", label: "Assumptions" },
  { key: "edits", label: "Edits" },
  { key: "reviews", label: "Reviews" },
] as const;

/** `/opportunities/{id}/trace?subject=estimates.estimate_line&subject_id={line}`: the line's
 * trace events (**Open in Trace**). */
export function lineTraceHref(opportunityId: string, lineId: string): string {
  const query = new URLSearchParams({ subject: "estimates.estimate_line", subject_id: lineId });
  return `/opportunities/${opportunityId}/trace?${query.toString()}`;
}

/** `/opportunities/{id}/trace?subject=estimates.assumption&subject_id={assumption}`: the
 * Assumption's own trace events and the Actuals that recorded it as failed (Story 10.4,
 * **Open in Trace** from a failed Assumption). */
export function assumptionTraceHref(opportunityId: string, assumptionId: string): string {
  const query = new URLSearchParams({ subject: "estimates.assumption", subject_id: assumptionId });
  return `/opportunities/${opportunityId}/trace?${query.toString()}`;
}

/** "Condition · A2" / "Contingency · A3" (a failed Assumption's label); "Condition" when its
 * number isn't known. */
export function failedKindLabel(kind: string, position: number | null | undefined): string {
  const name = kind === "contingency" ? "Contingency" : "Condition";
  return position == null ? name : `${name} · A${position}`;
}

/** A failed Assumption's text: the wording, or for a Contingency "{h} h · wording". */
export function failedAssumptionText(assumption: {
  kind: string;
  wording: string;
  amount_hours?: number | null;
}): string {
  return assumption.kind === "contingency" && assumption.amount_hours != null
    ? `${hours(assumption.amount_hours)} h · ${assumption.wording}`
    : assumption.wording;
}

/** "Accepted by {name} · {date}", or "Not accepted". */
export function failedAcceptedLabel(assumption: {
  accepted_by?: { name: string } | null;
  accepted_at?: string | null;
}): string {
  if (!assumption.accepted_by) return NOT_ACCEPTED;
  const name = assumption.accepted_by.name;
  return assumption.accepted_at
    ? `Accepted by ${name} · ${registerDate(assumption.accepted_at)}`
    : `Accepted by ${name}`;
}

/** A delta in hours for a Total cell: "+4.0 h", "−4.0 h" (a minus sign), or "no change". */
export function deltaText(delta: number): string {
  const rounded = Math.round(delta * 10) / 10;
  if (rounded > 0) return `+${hours(rounded)} h`;
  if (rounded < 0) return `−${hours(Math.abs(rounded))} h`;
  return NO_CHANGE;
}

/** "Diff vs v2" (the toolbar toggle). */
export function diffToggleLabel(version: number): string {
  return `Diff vs v${version}`;
}

/** "Compared with v2" (the right pane's heading). */
export function comparedWith(version: number): string {
  return `Compared with v${version}`;
}

/** "Comparing v3 with v2" (announced when the diff turns on or changes). */
export function comparingAnnouncement(shown: number, against: number): string {
  return `Comparing v${shown} with v${against}`;
}

/** The version a diff compares against by default: the Baseline when one exists and the
 * shown version is later, else the version numbered just before (null: none). */
export function defaultDiffTarget(
  versions: readonly Pick<VersionListItem, "version" | "is_baseline">[],
  shown: number,
): number | null {
  const baseline = versions.find((v) => v.is_baseline);
  if (baseline && baseline.version < shown) return baseline.version;
  const earlier = versions.filter((v) => v.version < shown).map((v) => v.version);
  return earlier.length > 0 ? Math.max(...earlier) : null;
}

/** The versions a diff can compare against: every other version, the Baseline first, then
 * newest first (the API's order). */
export function diffTargets<T extends Pick<VersionListItem, "version">>(
  versions: readonly T[],
  shown: number,
): T[] {
  return versions.filter((v) => v.version !== shown);
}

/** `?diff=n` from the URL as a positive whole number, or null. */
export function parseDiffParam(search: string): number | null {
  return parseVersionParam(new URLSearchParams(search).get("diff"));
}

/** The current URL with `?diff=n` set (or removed for null), keeping everything else. */
export function withDiffParam(href: string, diff: number | null): string {
  const url = new URL(href);
  if (diff === null) url.searchParams.delete("diff");
  else url.searchParams.set("diff", String(diff));
  return `${url.pathname}${url.search}${url.hash}`;
}

function lineKey(section: string, title: string): string {
  return `${section}\u0000${title.trim().toLowerCase()}`;
}

/** The comparison's line diffs by the shown line's section and title (as the server matches
 * them); removed lines are left out (they have no row). */
export function lineDeltas(comparison: VersionComparison): Map<string, LineDiff> {
  const found = new Map<string, LineDiff>();
  for (const diff of comparison.lines) {
    if (diff.change !== "removed") found.set(lineKey(diff.section, diff.title), diff);
  }
  return found;
}

/** The line diff of a shown line, or null when it didn't change. */
export function lineDelta(
  deltas: Map<string, LineDiff>,
  line: Pick<EstimateLine, "section" | "title">,
): LineDiff | null {
  return deltas.get(lineKey(line.section, line.title)) ?? null;
}

/** "Superseded"-style words for a lineage actor and time: "Ana Reviewer · 21 Oct 2026". */
export function actorAndDate(
  actor: Pick<LineageActor, "name"> | null | undefined,
  at: string | null | undefined,
): string {
  return [actor?.name, at ? longDate(at) : null].filter(Boolean).join(" · ");
}

/** A finding or effort entry's heading: "Engineering Agent · Assessment v2". */
export function findingSource(finding: Pick<LineageFinding, "agent_label" | "entry" | "version">): string {
  const kind = finding.entry === "critic" || finding.entry === "red_team" ? "Review" : "Assessment";
  return `${finding.agent_label} · ${kind} v${finding.version}`;
}
