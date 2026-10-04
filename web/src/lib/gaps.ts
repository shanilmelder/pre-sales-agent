// Gap display helpers (Story 4.3 + 4.4, demo scope). Safe on server and client.
import type { components } from "@/lib/api/client";

export type Gap = components["schemas"]["Gap"];
export type GapList = components["schemas"]["GapList"];
export type GapRequirement = components["schemas"]["GapRequirement"];
export type GapCategory = components["schemas"]["GapCategory"];
export type Impact = components["schemas"]["Impact"];
export type Detection = components["schemas"]["Detection"];
export type DetectionErrorCode = components["schemas"]["DetectionErrorCode"];
export type ClarificationQuestion = components["schemas"]["ClarificationQuestion"];

/** The categories with their labels. */
export const GAP_CATEGORIES: readonly { value: GapCategory; label: string }[] = [
  { value: "data_volumes", label: "Data volumes" },
  { value: "versions_and_platforms", label: "Versions and platforms" },
  { value: "integration_details", label: "Integration details" },
  { value: "security_and_compliance", label: "Security and compliance" },
  { value: "non_functional", label: "Non-functional" },
  { value: "scope_and_ownership", label: "Scope and ownership" },
  { value: "commercial", label: "Commercial" },
  { value: "other", label: "Other" },
];

/** A category's label (its own name for one this build doesn't know). */
export function categoryLabel(value: GapCategory): string {
  return GAP_CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

/** Impacts high to low, with their labels and how many of the bar's 3 segments they fill. */
export const IMPACTS: readonly { value: Impact; label: string; level: 1 | 2 | 3 }[] = [
  { value: "high", label: "High", level: 3 },
  { value: "medium", label: "Medium", level: 2 },
  { value: "low", label: "Low", level: 1 },
];

export function impactLabel(value: Impact): string {
  return IMPACTS.find((i) => i.value === value)?.label ?? value;
}

/** How many of the impact bar's 3 segments are filled (0 for an impact this build doesn't
 * know). */
export function impactLevel(value: Impact): 0 | 1 | 2 | 3 {
  return IMPACTS.find((i) => i.value === value)?.level ?? 0;
}

/** The question pill: a drafted question reads "Draft". */
export const DRAFT = "Draft";

/** The header while a detection is queued or running. */
export const DETECTING = "Detecting Gaps";

/** The empty-state sentence. */
export const NO_GAPS = "Gaps appear here after Requirements are extracted.";

/** A finished detection that raised nothing. */
export const NONE_FOUND = "No Gaps were found in the Requirements.";

/** Shown instead of the running indicator once polling has stopped (15 minutes). */
export const STILL_DETECTING = "Still detecting — reload to check.";

/** "1 Gap", "3 Gaps". */
export function gapCount(n: number): string {
  return `${n} ${n === 1 ? "Gap" : "Gaps"}`;
}

/** Why a detection failed, as the Gaps tab says it. */
export const DETECTION_FAILURE_REASONS: Record<DetectionErrorCode, string> = {
  model_unavailable: "the model service couldn't be reached",
  model_timeout: "the model took too long to answer",
  output_invalid: "the model's answer couldn't be used",
};

/** "Gap detection failed: <reason>" (a general reason for a code this build doesn't know). */
export function detectionFailure(code: DetectionErrorCode | null | undefined): string {
  const reason =
    (code ? DETECTION_FAILURE_REASONS[code] : undefined) ?? "something went wrong";
  return `Gap detection failed: ${reason}`;
}

/** True while the detection is queued or running. */
export function isDetecting(detection: Detection | null | undefined): boolean {
  return detection?.status === "queued" || detection?.status === "running";
}

/** How often the Gaps tab re-reads the list while detecting. */
export const DETECTION_POLL_MS = 2000;

/** Polling stops after this long of continuous detecting (a reload resumes it). */
export const DETECTION_POLL_LIMIT_MS = 15 * 60 * 1000;
