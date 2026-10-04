// Requirement display helpers (Story 2.5 Part A). Safe on server and client.
import type { components } from "@/lib/api/client";

export type Requirement = components["schemas"]["Requirement"];
export type RequirementEvidence = components["schemas"]["RequirementEvidence"];
export type RequirementList = components["schemas"]["RequirementList"];
export type Classification = components["schemas"]["Classification"];
export type Extraction = components["schemas"]["Extraction"];
export type ExtractionStatus = components["schemas"]["ExtractionStatus"];
export type ExtractionErrorCode = components["schemas"]["ExtractionErrorCode"];

/** The classifications in the order the Requirements tab groups them, with their labels. */
export const CLASSIFICATIONS: readonly { value: Classification; label: string }[] = [
  { value: "functional", label: "Functional" },
  { value: "integration", label: "Integration" },
  { value: "data", label: "Data" },
  { value: "security", label: "Security" },
  { value: "non_functional", label: "Non-functional" },
  { value: "commercial", label: "Commercial" },
];

export type RequirementGroup = {
  classification: Classification;
  label: string;
  items: Requirement[];
};

/** The Requirements grouped by classification, in `CLASSIFICATIONS` order, keeping their
 * order within a group. Empty groups are left out; a classification this build doesn't know
 * is grouped last under its own name. */
export function groupRequirements(items: readonly Requirement[]): RequirementGroup[] {
  const groups: RequirementGroup[] = CLASSIFICATIONS.map(({ value, label }) => ({
    classification: value,
    label,
    items: items.filter((item) => item.classification === value),
  }));
  const known = new Set<string>(CLASSIFICATIONS.map((c) => c.value));
  for (const item of items) {
    if (known.has(item.classification)) continue;
    let group = groups.find((g) => g.classification === item.classification);
    if (!group) {
      group = { classification: item.classification, label: item.classification, items: [] };
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups.filter((group) => group.items.length > 0);
}

/** The header while an extraction is queued or running. */
export const EXTRACTING = "Extracting Requirements";

/** The empty-state sentence. */
export const NO_REQUIREMENTS = "Requirements appear here after Sources are parsed.";

/** What replaces Retry when the Sources are over the extraction's input budget. */
export const TOO_MUCH_TEXT = "Too much source text for one extraction — remove or shorten a Source.";

/** Shown instead of the running indicator once polling has stopped (15 minutes). */
export const STILL_EXTRACTING = "Still extracting — reload to check.";

/** "1 Requirement", "3 Requirements". */
export function requirementCount(n: number): string {
  return `${n} ${n === 1 ? "Requirement" : "Requirements"}`;
}

/** A finished extraction that found nothing: "No Requirements were found in 2 Sources." */
export function noneFound(sourceCount: number | null | undefined): string {
  const n = sourceCount ?? 0;
  return `No Requirements were found in ${n} ${n === 1 ? "Source" : "Sources"}.`;
}

/** Why an extraction failed, as the Requirements tab says it. */
export const EXTRACTION_FAILURE_REASONS: Record<ExtractionErrorCode, string> = {
  model_unavailable: "the model service couldn't be reached",
  model_timeout: "the model took too long to answer",
  output_invalid: "the model's answer couldn't be used",
  input_too_large: "the Sources are too long to process in one go",
};

/** "Extraction failed: <reason>" (a general reason for a code this build doesn't know). */
export function extractionFailure(code: ExtractionErrorCode | null | undefined): string {
  const reason =
    (code ? EXTRACTION_FAILURE_REASONS[code] : undefined) ?? "something went wrong";
  return `Extraction failed: ${reason}`;
}

/** True while the extraction is queued or running. */
export function isExtracting(extraction: Extraction | null | undefined): boolean {
  return extraction?.status === "queued" || extraction?.status === "running";
}

/** How often the Requirements tab re-reads the list while extracting. */
export const EXTRACTION_POLL_MS = 2000;

/** Polling stops after this long of continuous extracting (a reload resumes it). */
export const EXTRACTION_POLL_LIMIT_MS = 15 * 60 * 1000;
