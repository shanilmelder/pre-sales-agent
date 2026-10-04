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
export const ROLES: readonly { value: RoleName; label: string; short: string }[] = [
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

/** "Draft v2". */
export function versionLabel(version: Pick<EstimateVersion, "status" | "version">): string {
  const status = version.status === "draft" ? "Draft" : "Superseded";
  return `${status} v${version.version}`;
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
export const NOTHING_TO_ESTIMATE = "There were no active Requirements to estimate.";

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
  const reason = (code ? DRAFT_FAILURE_REASONS[code] : undefined) ?? "something went wrong";
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
