// Gap display helpers (Story 4.3 + 4.4, demo scope; Story 4.5 question edits; Story 4.4
// impact change, dismiss, reopen and history). Safe on server and client.
import {
  ArrowRightIcon,
  CheckIcon,
  CircleHelpIcon,
  MinusIcon,
  PencilLineIcon,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";
import { registerDate } from "@/lib/estimates";
import { codePointLength, type StatusTone } from "@/lib/opportunities";

export type Gap = components["schemas"]["Gap"];
export type GapList = components["schemas"]["GapList"];
export type GapRequirement = components["schemas"]["GapRequirement"];
export type GapCategory = components["schemas"]["GapCategory"];
export type Impact = components["schemas"]["Impact"];
export type Detection = components["schemas"]["Detection"];
export type DetectionErrorCode = components["schemas"]["DetectionErrorCode"];
export type ClarificationQuestion = components["schemas"]["ClarificationQuestion"];
export type QuestionStatus = components["schemas"]["QuestionStatus"];
export type GapStatus = components["schemas"]["GapStatus"];
export type GapDismissal = components["schemas"]["GapDismissal"];
export type GapHistoryEntry = components["schemas"]["GapHistoryEntry"];
export type DismissReasonKind = components["schemas"]["DismissReasonKind"];

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

/** The question pill: a drafted question reads "Draft", an approved one "Approved". */
export const DRAFT = "Draft";
export const APPROVED = "Approved";

/** The question statuses the pill shows, with their label, icon and icon tone (the pill always
 * shows icon and label). */
export const QUESTION_STATUSES: Record<
  "drafted" | "approved",
  { label: string; icon: LucideIcon; tone: StatusTone }
> = {
  drafted: { label: DRAFT, icon: PencilLineIcon, tone: "text-muted-foreground" },
  approved: { label: APPROVED, icon: CheckIcon, tone: "text-resolved" },
};

/** A question status's pill (Draft for one this build doesn't know). */
export function questionStatus(status: QuestionStatus): {
  label: string;
  icon: LucideIcon;
  tone: StatusTone;
} {
  return status === "approved" ? QUESTION_STATUSES.approved : QUESTION_STATUSES.drafted;
}

/** The API's longest question text and topic, in code points (trimmed). */
export const QUESTION_MAX = 1000;
export const TOPIC_MAX = 80;

/** Why a question text can't be saved, or null. */
export function questionTextProblem(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return "The question can't be blank.";
  if (codePointLength(trimmed) > QUESTION_MAX) return "The question can be at most 1,000 characters.";
  return null;
}

/** Why a topic can't be saved, or null. */
export function questionTopicProblem(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return "The topic can't be blank.";
  if (codePointLength(trimmed) > TOPIC_MAX) return "The topic can be at most 80 characters.";
  return null;
}

/** "Approved by Jane Doe, 5 Oct 2026". */
export function approvedLabel(
  question: Pick<ClarificationQuestion, "approved_by" | "approved_at">,
): string {
  const name = question.approved_by?.name ?? "someone";
  return question.approved_at
    ? `Approved by ${name}, ${registerDate(question.approved_at)}`
    : `Approved by ${name}`;
}

/** "Draft since 5 Oct 2026" / "Approved since 5 Oct 2026": the last status change. */
export function statusSince(question: Pick<ClarificationQuestion, "status" | "status_changed_at">) {
  return `${questionStatus(question.status).label} since ${registerDate(question.status_changed_at)}`;
}

/** The open Gaps whose question is drafted: what **Approve all** approves. */
export function toApprove(items: readonly Gap[]): Gap[] {
  return items.filter((g) => g.status === "open" && g.question?.status === "drafted");
}

/** "Approve all (3)". */
export function approveAllLabel(n: number): string {
  return `Approve all (${n})`;
}

/** "1 question approved", "3 questions approved". */
export function approvedCount(n: number): string {
  return `${n} ${n === 1 ? "question" : "questions"} approved`;
}

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
  registry_agent_disabled: "its agent is disabled",
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

// --- Gap status, impact change, dismiss and reopen (Story 4.4) -------------------------------

/** The Gap statuses the list shows, with label, icon and icon tone (UX status pills: Open is
 * circle-help in gap amber; Converted arrow-right and Dismissed minus, both neutral). */
export const GAP_STATUSES: Record<
  "open" | "converted" | "dismissed",
  { label: string; icon: LucideIcon; tone: StatusTone }
> = {
  open: { label: "Open", icon: CircleHelpIcon, tone: "text-gap" },
  converted: { label: "Converted", icon: ArrowRightIcon, tone: "text-muted-foreground" },
  dismissed: { label: "Dismissed", icon: MinusIcon, tone: "text-muted-foreground" },
};

/** A Gap status's icon and label (Open for one this build doesn't know). */
export function gapStatus(status: GapStatus): {
  label: string;
  icon: LucideIcon;
  tone: StatusTone;
} {
  return status === "converted" || status === "dismissed"
    ? GAP_STATUSES[status]
    : GAP_STATUSES.open;
}

/** "Clarification Agent · Data volumes": what raised the Gap. */
export function triggerLabel(gap: Pick<Gap, "category">): string {
  return `Clarification Agent · ${categoryLabel(gap.category)}`;
}

/** "9 Gaps · 7 open · ranked by impact". */
export function gapsSummary(items: readonly Pick<Gap, "status">[]): string {
  const open = items.filter((g) => g.status === "open").length;
  return `${gapCount(items.length)} · ${open} open · ranked by impact`;
}

/** "Approve 2 selected". */
export function approveSelectedLabel(n: number): string {
  return `Approve ${n} selected`;
}

/** The API's longest reason or note, in code points (trimmed). */
export const REASON_MAX = 500;

/** Why a required reason can't be sent, or null. */
export function reasonProblem(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return REASON_REQUIRED;
  if (codePointLength(trimmed) > REASON_MAX) return "The reason can be at most 500 characters.";
  return null;
}

export const REASON_REQUIRED = "Give a reason.";
export const NOTE_REQUIRED = "Say why: a note is needed for “Other”.";

/** Why a dismissal's note can't be sent, or null: required for `other`, optional for
 * `not_relevant`. */
export function noteProblem(kind: DismissReasonKind, raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return kind === "other" ? NOTE_REQUIRED : null;
  if (codePointLength(trimmed) > REASON_MAX) return "The note can be at most 500 characters.";
  return null;
}

/** The dismissal reasons with their labels. */
export const DISMISS_REASONS: readonly { value: DismissReasonKind; label: string }[] = [
  { value: "not_relevant", label: "Not relevant" },
  { value: "other", label: "Other" },
];

export function dismissReasonLabel(kind: DismissReasonKind): string {
  return DISMISS_REASONS.find((r) => r.value === kind)?.label ?? kind;
}

/** "Dismissed · Not relevant · Jane Doe, 14 Oct 2026". */
export function dismissedLabel(dismissal: GapDismissal): string {
  return `Dismissed · ${dismissReasonLabel(dismissal.reason_kind)} · ${dismissal.by.name}, ${registerDate(dismissal.at)}`;
}

/** What a history entry says happened, e.g. "Impact changed from High to Low". */
export function historyAction(entry: GapHistoryEntry): string {
  switch (entry.kind) {
    case "raised":
      return "Raised by Clarification Agent";
    case "impact_changed":
      return entry.old_impact && entry.new_impact
        ? `Impact changed from ${impactLabel(entry.old_impact)} to ${impactLabel(entry.new_impact)}`
        : "Impact changed";
    case "dismissed":
      return entry.reason_kind
        ? `Dismissed: ${dismissReasonLabel(entry.reason_kind)}`
        : "Dismissed";
    case "reopened":
      return "Reopened";
    case "converted":
      return "Converted to Assumption";
    default:
      return "Changed";
  }
}

/** "Jane Doe, 14 Oct 2026" (the agent's own entry names no person). */
export function historyByline(entry: GapHistoryEntry): string {
  const date = registerDate(entry.at);
  return entry.actor === "agent" ? date : `${entry.actor.name}, ${date}`;
}

const STATUS_ORDER: Record<string, number> = { open: 0, converted: 1, dismissed: 2 };

/** Open Gaps, then converted, then dismissed; each ranked by impact, then oldest first (the
 * API's order, kept after a local change). */
export function rankGaps(items: readonly Gap[]): Gap[] {
  const rank = (impact: Impact) => IMPACTS.findIndex((i) => i.value === impact);
  return [...items].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3) ||
      rank(a.impact) - rank(b.impact) ||
      a.created_at.localeCompare(b.created_at) ||
      a.id.localeCompare(b.id),
  );
}
