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

/** Where a Requirement came from, as its row and the inspector say it: "Extracted", "Edited
 * by Ann Lee" once a person changed it ("Edited" when the API doesn't name them), or "Added by
 * a person" for one a person created (`human` with no Evidence, Story 2.6). */
export function originLine(
  item: Pick<Requirement, "origin" | "evidence" | "last_changed_by">,
): string {
  if (item.origin === "extracted") return "Extracted";
  if (item.evidence.length === 0) return ADDED_BY_A_PERSON;
  return item.last_changed_by ? `Edited by ${item.last_changed_by.name}` : "Edited";
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

export const ADDED_BY_A_PERSON = "Added by a person";
export const NO_EVIDENCE = "No Evidence.";
export const ADD_REQUIREMENT = "Add requirement";
export const SPLIT_REQUIREMENT = "Split";
export const EDIT = "Edit";
export const MERGE = "Merge";
export const SELECTED_FOR_MERGE = "Selected for merge";
export const CONFIRM_REQUIREMENT = "Confirm requirement";
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

// --- state, counts and filters (the Requirements tab redesign) ---------------------------------

/** A Requirement's state as its pill shows it: a pending change outranks confirmation. */
export type RequirementState = "confirmed" | "unconfirmed" | "pending";

export const REQUIREMENT_STATES: readonly { value: RequirementState; label: string }[] = [
  { value: "confirmed", label: CONFIRMED },
  { value: "unconfirmed", label: "Unconfirmed" },
  { value: "pending", label: PENDING_CHANGE },
];

export function requirementState(
  item: Pick<Requirement, "confirmed_at" | "pending_change">,
): RequirementState {
  if (item.pending_change) return "pending";
  return item.confirmed_at ? "confirmed" : "unconfirmed";
}

export function stateLabel(state: RequirementState): string {
  return REQUIREMENT_STATES.find((s) => s.value === state)?.label ?? state;
}

/** How many Requirements there are, how many are confirmed (as their pills say: one with a
 * pending change is not) and how many are left to review (the rest). */
export function requirementCounts(items: readonly Requirement[]): {
  total: number;
  confirmed: number;
  toReview: number;
} {
  const confirmed = items.filter((item) => requirementState(item) === "confirmed").length;
  return { total: items.length, confirmed, toReview: items.length - confirmed };
}

/** The tab heading's counts: "5 total · 3 confirmed · 2 to review". */
export function countsLine(items: readonly Requirement[]): string {
  const { total, confirmed, toReview } = requirementCounts(items);
  return `${total} total · ${confirmed} confirmed · ${toReview} to review`;
}

/** A group heading's counts: "4 · 3 confirmed". */
export function groupSummary(items: readonly Requirement[]): string {
  return `${items.length} · ${requirementCounts(items).confirmed} confirmed`;
}

/** The banner over the list: "1 pending change from incremental intake". */
export function pendingChangesTitle(n: number): string {
  return `${n} pending ${n === 1 ? "change" : "changes"} from incremental intake`;
}

/** The tab's client-side filters; null shows every value. */
export type RequirementFilters = {
  category: Classification | null;
  state: RequirementState | null;
};

export const NO_FILTERS: RequirementFilters = { category: null, state: null };
export const NO_MATCH = "No Requirements match these filters.";
export const CLEAR_FILTERS = "Clear filters";
/** The banner's link that opens a changed Requirement in the inspector. */
export const REVIEW = "Review";

/** The Requirements the filters let through, in their order. */
export function filterRequirements(
  items: readonly Requirement[],
  filters: RequirementFilters,
): Requirement[] {
  return items.filter(
    (item) =>
      (filters.category === null || item.classification === filters.category) &&
      (filters.state === null || requirementState(item) === filters.state),
  );
}

/** The Category filter's choices: the classifications present, in grouping order. */
export function categoriesPresent(
  items: readonly Requirement[],
): { value: Classification; label: string }[] {
  return groupRequirements(items).map(({ classification, label }) => ({
    value: classification,
    label,
  }));
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
