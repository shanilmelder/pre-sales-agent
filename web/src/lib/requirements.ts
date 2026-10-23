// Requirement display helpers (Story 2.5 Part A). Safe on server and client.
import type { components } from "@/lib/api/client";

export type Requirement = components["schemas"]["Requirement"];
export type RequirementEvidence = components["schemas"]["RequirementEvidence"];
export type RequirementList = components["schemas"]["RequirementList"];
export type Classification = components["schemas"]["Classification"];
export type Extraction = components["schemas"]["Extraction"];
export type ExtractionStatus = components["schemas"]["ExtractionStatus"];
export type ExtractionErrorCode = components["schemas"]["ExtractionErrorCode"];
export type Passage = components["schemas"]["Passage"];
export type RequirementOrigin = components["schemas"]["RequirementOrigin"];
export type PendingChange = components["schemas"]["PendingChange"];
export type OutdatedAssessment = components["schemas"]["OutdatedAssessment"];
export type SplitResult = components["schemas"]["SplitResult"];

/** The classifications in the order the Requirements tab groups them, with their labels. */
export const CLASSIFICATIONS: readonly { value: Classification; label: string }[] = [
  { value: "functional", label: "Functional" },
  { value: "integration", label: "Integration" },
  { value: "data", label: "Data" },
  { value: "security", label: "Security" },
  { value: "non_functional", label: "Non-functional" },
  { value: "commercial", label: "Commercial" },
];

/** A classification's label (its own name for one this build doesn't know). */
export function classificationLabel(value: Classification): string {
  return CLASSIFICATIONS.find((c) => c.value === value)?.label ?? value;
}

/** A Requirement's origin as the list and inspector show it: a person's edit is "Edited",
 * and one a person added (`human` with no Evidence, Story 2.6) is "Manual". */
export function originLabel(origin: RequirementOrigin, evidenceCount?: number): string {
  if (origin === "extracted") return "Extracted";
  return evidenceCount === 0 ? MANUAL : "Edited";
}

/** The origin label of a Requirement as it stands. */
export function requirementOrigin(item: Pick<Requirement, "origin" | "evidence">): string {
  return originLabel(item.origin, item.evidence.length);
}

/** A Requirement's stable label: "R4". */
export function requirementLabel(item: Pick<Requirement, "number">): string {
  return `R${item.number}`;
}

// --- editing and confirming (Story 2.6) -------------------------------------------------------

/** The most characters (code points) a Requirement's text may have once trimmed. */
export const REQUIREMENT_TEXT_MAX = 2000;

/** The label of a confirmed Requirement. */
export const CONFIRMED = "Confirmed";

/** The Requirements not confirmed yet. */
export function unconfirmed(items: readonly Requirement[]): Requirement[] {
  return items.filter((item) => !item.confirmed_at);
}

/** The tab header's button: "Confirm all (3)". */
export function confirmAllLabel(n: number): string {
  return `Confirm all (${n})`;
}

/** Why a Requirement's text can't be saved, or null when it can (trimmed, 1 to 2,000 code
 * points; the API checks again). */
export function requirementTextProblem(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return "The Requirement text can't be blank.";
  if (Array.from(trimmed).length > REQUIREMENT_TEXT_MAX) {
    return "The Requirement text can be at most 2,000 characters.";
  }
  return null;
}

// --- shaping the list (Story 2.6) ------------------------------------------------------------

export const MANUAL = "Manual";
export const NO_EVIDENCE = "No Evidence.";
export const ADD_REQUIREMENT = "Add Requirement";
export const SPLIT_REQUIREMENT = "Split";
export const DELETE_REQUIREMENT = "Delete";
export const DELETE_REASON_LABEL = "Why delete this Requirement?";
export const VIEW_DIFF = "View diff";
export const HIDE_DIFF = "Hide diff";

/** The selection bar's button: "Merge (2)". */
export function mergeLabel(n: number): string {
  return `Merge (${n})`;
}

/** What the Merge form starts with: the selected texts joined by a space, and the first
 * one's classification. */
export function mergeDraft(selected: readonly Requirement[]): {
  text: string;
  classification: Classification;
} {
  return {
    text: selected.map((item) => item.text).join(" "),
    classification: selected[0]?.classification ?? "functional",
  };
}

// --- pending changes (Story 2.7) ----------------------------------------------------------------

/** The amber marker on a Requirement with a pending change, and its inspector section. */
export const PENDING_CHANGE = "Pending change";
export const ACCEPT_CHANGE = "Accept";
export const REJECT_CHANGE = "Reject";
export const REJECT_REASON_LABEL = "Why reject this change?";
export const CHANGE_DECIDED =
  "This change was already accepted or rejected. The Requirements were reloaded.";

/** "Classification: Functional → Integration", or null when the change keeps it. */
export function classificationChange(
  current: Classification,
  proposed: Classification,
): string | null {
  if (current === proposed) return null;
  return `Classification: ${classificationLabel(current)} → ${classificationLabel(proposed)}`;
}

/** "Engineering Agent (R1, R3)". */
export function outdatedLabel(item: OutdatedAssessment): string {
  return `${item.label} (${item.requirement_labels.join(", ")})`;
}

/** The Requirements tab's notice: "These Assessments used Requirements that have changed
 * since: Engineering Agent (R1), PM Agent (R2)." */
export function outdatedNotice(items: readonly OutdatedAssessment[]): string {
  return `These Assessments used Requirements that have changed since: ${items
    .map(outdatedLabel)
    .join(", ")}.`;
}

/** The Evidence inspector's passage states (Story 2.5 Part B). */
export const LOADING_PASSAGE = "Loading passage…";
export const PASSAGE_FAILED = "The passage couldn't be loaded.";
export const PASSAGE_GONE = "This passage is no longer available.";

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

/** The empty-tab card's title; the sentence is `NO_REQUIREMENTS_BODY`. */
export const NO_REQUIREMENTS = "No Requirements yet";
export const NO_REQUIREMENTS_BODY = "Requirements appear after the first Source is parsed.";
export const ADD_A_SOURCE = "Add a Source";

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
  registry_agent_disabled: "its agent is disabled",
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

// --- Integration Type tags (Story 4.1) --------------------------------------------------------

export type RequirementIntegrationType = components["schemas"]["RequirementIntegrationType"];

export const INTEGRATION_TYPES = "Integration Types";
export const NO_INTEGRATION_TYPES = "None";
export const TAG_SAVED = "Integration Types saved";
/** The `?untagged=` value that lists only integration Requirements with no Integration Type. */
export const UNTAGGED_INTEGRATION = "integration";
export const SHOW_ALL = "Show all";

/** An active Requirement classified `integration` with no Integration Type. */
export function isUntaggedIntegration(
  item: Pick<Requirement, "classification" | "integration_types">,
): boolean {
  return item.classification === "integration" && item.integration_types.length === 0;
}

/** The `?untagged=integration` status bar. */
export function untaggedFilterStatus(n: number): string {
  const noun = n === 1 ? "Requirement" : "Requirements";
  return `Showing ${n} integration ${noun} with no Integration Type`;
}
