// Gap display helpers (Story 4.3 + 4.4, demo scope; Story 4.5 question edits; Story 4.4
// impact change, dismiss, reopen and history). Safe on server and client.
import {
  ArrowRightIcon,
  CheckIcon,
  CircleHelpIcon,
  CircleSlashIcon,
  MinusIcon,
  PencilLineIcon,
  SendIcon,
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
export type QuestionExportFormat = components["schemas"]["QuestionExportRequest"]["format"];
export type GapAnswer = components["schemas"]["GapAnswer"];
export type AnswerSuggestion = components["schemas"]["AnswerSuggestion"];
export type AnswerPassage = components["schemas"]["AnswerPassage"];
export type RequirementChangeRef = components["schemas"]["RequirementChangeRef"];
export type GapsContext = components["schemas"]["GapsContext"];
export type GapsContextChecklist = components["schemas"]["GapsContextChecklist"];

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

/** The question pill: a drafted question reads "Draft", an approved one "Approved", a sent one
 * "Sent" and one the customer won't answer "No answer" (Story 4.6). */
export const DRAFT = "Draft";
export const APPROVED = "Approved";
export const SENT = "Sent";
export const NO_ANSWER = "No answer";
export const ANSWERED = "Answered";

export type PillStatus = "drafted" | "approved" | "sent" | "unanswered" | "answered";

/** A question pill's tone: a status tone, or the primary tint (Sent). */
export type QuestionTone = StatusTone | "text-primary";

/** The question statuses the pill shows, with their label, icon and tone (the pill always
 * shows icon and label): Draft neutral, Approved and Answered resolved, Sent primary, No answer
 * gap amber. */
export const QUESTION_STATUSES: Record<
  PillStatus,
  { label: string; icon: LucideIcon; tone: QuestionTone }
> = {
  drafted: { label: DRAFT, icon: PencilLineIcon, tone: "text-muted-foreground" },
  approved: { label: APPROVED, icon: CheckIcon, tone: "text-resolved" },
  sent: { label: SENT, icon: SendIcon, tone: "text-primary" },
  unanswered: { label: NO_ANSWER, icon: CircleSlashIcon, tone: "text-gap" },
  answered: { label: ANSWERED, icon: CheckIcon, tone: "text-resolved" },
};

/** A question status's pill (Draft for one this build doesn't know). */
export function questionStatus(status: QuestionStatus): {
  label: string;
  icon: LucideIcon;
  tone: QuestionTone;
} {
  return status in QUESTION_STATUSES
    ? QUESTION_STATUSES[status as PillStatus]
    : QUESTION_STATUSES.drafted;
}

/** Whether a question was sent (sent, "No answer" or answered): it can no longer be edited or
 * approved. */
export function isSent(status: QuestionStatus): boolean {
  return status === "sent" || status === "unanswered" || status === "answered";
}

/** Whether a question can be answered (Story 4.7): sent or "No answer". */
export function isAnswerable(status: QuestionStatus | undefined): boolean {
  return status === "sent" || status === "unanswered";
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

/** "Sent 14 Oct 2026 by Jane Doe" (Story 4.6). */
export function sentLabel(question: Pick<ClarificationQuestion, "sent_on" | "sent_by">): string {
  const date = question.sent_on ? ` ${registerDate(question.sent_on)}` : "";
  return `Sent${date} by ${question.sent_by?.name ?? "someone"}`;
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

// --- exporting and sending questions (Story 4.6) ----------------------------------------------

/** The open Gaps whose question is approved: what is exported and what **Mark all sent**
 * marks. */
export function toSend(items: readonly Gap[]): Gap[] {
  return items.filter((g) => g.status === "open" && g.question?.status === "approved");
}

/** "Mark all sent (3)". */
export function markAllSentLabel(n: number): string {
  return `Mark all sent (${n})`;
}

/** "Mark 2 selected sent". */
export function markSelectedSentLabel(n: number): string {
  return `Mark ${n} selected sent`;
}

/** "1 question marked sent", "3 questions marked sent". */
export function sentCount(n: number): string {
  return `${n} ${n === 1 ? "question" : "questions"} marked sent`;
}

/** "1 question copied", "3 questions copied". */
export function copiedCount(n: number): string {
  return `${n} ${n === 1 ? "question" : "questions"} copied`;
}

/** The export formats of the approved questions, in the menu's order. */
export const QUESTION_EXPORT_FORMATS: readonly { value: QuestionExportFormat; label: string }[] = [
  { value: "copy", label: "Copy" },
  { value: "docx", label: "Word (.docx)" },
  { value: "eml", label: "Email draft (.eml)" },
];

/** The web route that downloads a `.docx` or `.eml` export (it adds the user's token and fetches
 * the signed link server-side). */
export function questionsExportUrl(opportunityId: string, format: "docx" | "eml"): string {
  return `/api/opportunities/${encodeURIComponent(opportunityId)}/questions-export?format=${format}`;
}

/** Why an export of questions failed, by HTTP status and problem code. */
export function questionsExportFailureReason(status: number | null, code?: string | null): string {
  if (status === null || status === 502) return "the export service couldn't be reached";
  if (status === 401) return "your session has expired; reload the page";
  if (status === 403) return "only the owner and collaborators can export questions";
  if (status === 404) return "you no longer have access to this Opportunity";
  if (status === 409 || code === "no_approved_questions") {
    return "there are no approved questions to export";
  }
  return "the file couldn't be created";
}

/** Today's date where the user is, as `YYYY-MM-DD` (the default "date sent"). */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Why a "date sent" can't be sent, or null: required, and not after `today`. */
export function sentOnProblem(value: string, today: string = localToday()): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Give the date the questions were sent.";
  if (value > today) return "The date sent can't be in the future.";
  return null;
}

/** "1 question approved", "3 questions approved". */
export function approvedCount(n: number): string {
  return `${n} ${n === 1 ? "question" : "questions"} approved`;
}

/** The header while a detection is queued or running. */
export const DETECTING = "Detecting Gaps";

/** The empty-tab card's title; the sentence is `NO_GAPS_BODY`. */
export const NO_GAPS = "No Gaps";
export const NO_GAPS_BODY = "Gaps appear after Requirements are checked against Checklists.";
export const OPEN_REQUIREMENTS = "Open Requirements";

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

/** How often the Gaps tab re-reads the list while the event stream is not connected (Story
 * 4.7: polling is the fallback for live updates). */
export const GAPS_FALLBACK_POLL_MS = 10_000;

// --- Gap status, impact change, dismiss and reopen (Story 4.4) -------------------------------

/** The Gap statuses the list shows, with label, icon and icon tone (UX status pills: Open is
 * circle-help in gap amber; Converted arrow-right and Dismissed minus, both neutral). */
export const GAP_STATUSES: Record<
  "open" | "answered" | "converted" | "dismissed",
  { label: string; icon: LucideIcon; tone: StatusTone }
> = {
  open: { label: "Open", icon: CircleHelpIcon, tone: "text-gap" },
  answered: { label: ANSWERED, icon: CheckIcon, tone: "text-resolved" },
  converted: { label: "Converted", icon: ArrowRightIcon, tone: "text-muted-foreground" },
  dismissed: { label: "Dismissed", icon: MinusIcon, tone: "text-muted-foreground" },
};

/** A Gap status's icon and label (Open for one this build doesn't know). */
export function gapStatus(status: GapStatus): {
  label: string;
  icon: LucideIcon;
  tone: StatusTone;
} {
  return status === "converted" || status === "dismissed" || status === "answered"
    ? GAP_STATUSES[status]
    : GAP_STATUSES.open;
}

/** The agent that raises Gaps: the trigger pill's text. */
export const CLARIFICATION_AGENT = "Clarification Agent";

/** The trigger pill's text in a row: "Clarification Agent", or for a mandatory Checklist item
 * (Story 4.2) "Checklist · Security baseline v2". */
export function triggerSource(gap: Pick<Gap, "trigger">): string {
  if (gap.trigger.kind === "checklist_item") {
    return `Checklist · ${gap.trigger.checklist_name} v${gap.trigger.version}`;
  }
  return CLARIFICATION_AGENT;
}

/** What raised the Gap: "Clarification Agent · Data volumes", or for a mandatory Checklist
 * item (Story 4.2) "Checklist · Security baseline v2". */
export function triggerLabel(gap: Pick<Gap, "category" | "trigger">): string {
  if (gap.trigger.kind === "checklist_item") return triggerSource(gap);
  return `${CLARIFICATION_AGENT} · ${categoryLabel(gap.category)}`;
}

/** Raised from a mandatory Checklist item (Story 4.2). */
export function isMandatory(gap: Pick<Gap, "origin">): boolean {
  return gap.origin === "mandatory_checklist";
}

/** A mandatory Gap whose Checklist no longer applies: it is kept, and may be dismissed. */
export function checklistNoLongerApplies(gap: Pick<Gap, "origin" | "checklist_applies">): boolean {
  return isMandatory(gap) && !gap.checklist_applies;
}

/** Whether Dismiss is offered: never for a mandatory Gap while its Checklist still applies. */
export function canDismiss(gap: Pick<Gap, "origin" | "checklist_applies">): boolean {
  return !isMandatory(gap) || !gap.checklist_applies;
}

export const NO_LONGER_APPLIES = "Checklist no longer applies";
/** Next to a question drafted from the Checklist item's wording (Story 4.2). */
export const FROM_CHECKLIST = "from Checklist";

/** "9 total · 7 open · ranked by impact", plus " · showing 2" while a filter hides some
 * (`showing` is the number of rows shown; left out when no filter is on). */
export function gapsSummary(items: readonly Pick<Gap, "status">[], showing?: number): string {
  const open = items.filter((g) => g.status === "open").length;
  const shown = showing === undefined ? "" : ` · showing ${showing}`;
  return `${items.length} total · ${open} open · ranked by impact${shown}`;
}

/** The text tone of an impact: High blocker red, Medium gap amber, Low neutral. */
export function impactTone(impact: Impact): "text-blocker" | "text-gap" | "text-neutral" {
  return impact === "high" ? "text-blocker" : impact === "medium" ? "text-gap" : "text-neutral";
}

/** The muted line under the inspector's primary action: where the question is in its flow. */
export function questionFlow(status: QuestionStatus | "dismissed"): string | null {
  switch (status) {
    case "drafted":
      return "Draft, then Approved, Sent and Answered.";
    case "approved":
      return "Approved. Export it, send it to the customer, then mark it sent.";
    case "sent":
    case "unanswered":
      return "Sent. Record the customer answer to close this Gap.";
    case "answered":
      return "Answered. Related Requirements have proposed updates.";
    case "dismissed":
      return "Dismissed with a reason.";
    default:
      return null;
  }
}

// --- filters (client-side, not persisted) ---------------------------------------------------

/** The Gaps tab's filters: null is "Any". They combine with AND. */
export type GapFilters = {
  impact: Impact | null;
  category: GapCategory | null;
  question: PillStatus | null;
};

export const NO_GAP_FILTERS: GapFilters = { impact: null, category: null, question: null };

/** The Impact filter's options (after Any). */
export const IMPACT_FILTER_OPTIONS: readonly { value: Impact; label: string }[] = IMPACTS.map(
  ({ value, label }) => ({ value, label }),
);

/** The Question status filter's options (after Any). */
export const QUESTION_FILTER_OPTIONS: readonly { value: PillStatus; label: string }[] = (
  ["drafted", "approved", "sent", "unanswered", "answered"] as const
).map((value) => ({ value, label: QUESTION_STATUSES[value].label }));

/** The Area filter's options (after Any): the categories present in `items`, in the
 * categories' order (one this build doesn't know last, by its own name). */
export function areaFilterOptions(
  items: readonly Pick<Gap, "category">[],
): { value: GapCategory; label: string }[] {
  const present = new Set(items.map((g) => g.category));
  const known = GAP_CATEGORIES.filter((c) => present.has(c.value));
  const unknown = [...present]
    .filter((value) => !GAP_CATEGORIES.some((c) => c.value === value))
    .map((value) => ({ value, label: categoryLabel(value) }));
  return [...known, ...unknown];
}

/** Whether any filter is on. */
export function hasGapFilters(filters: GapFilters): boolean {
  return filters.impact !== null || filters.category !== null || filters.question !== null;
}

/** The Gaps that pass every filter, in their order. */
export function filterGaps<T extends Pick<Gap, "impact" | "category" | "question">>(
  items: readonly T[],
  filters: GapFilters,
): T[] {
  return items.filter(
    (g) =>
      (filters.impact === null || g.impact === filters.impact) &&
      (filters.category === null || g.category === filters.category) &&
      (filters.question === null || g.question?.status === filters.question),
  );
}

export const NO_FILTER_MATCH = "No Gaps match these filters.";
export const CLEAR_FILTERS = "Clear filters";

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
export function historyAction(
  entry: GapHistoryEntry,
  convertedTo?: Gap["converted_to"],
): string {
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
      return convertedTo === "risk" ? "Converted to Risk" : "Converted to Assumption";
    case "answered":
      return "Answered";
    default:
      return "Changed";
  }
}

/** "Jane Doe, 14 Oct 2026" (the agent's own entry names no person). */
export function historyByline(entry: GapHistoryEntry): string {
  const date = registerDate(entry.at);
  return entry.actor === "agent" ? date : `${entry.actor.name}, ${date}`;
}

const STATUS_ORDER: Record<string, number> = { open: 0, answered: 1, converted: 2, dismissed: 3 };

/** Open Gaps, then answered, then converted, then dismissed; each ranked by impact, mandatory
 * first within an impact (Story 4.2), then oldest first (the API's order, kept after a local
 * change). */
export function rankGaps(items: readonly Gap[]): Gap[] {
  const rank = (impact: Impact) => IMPACTS.findIndex((i) => i.value === impact);
  const mandatory = (gap: Gap) => (isMandatory(gap) ? 0 : 1);
  return [...items].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 4) - (STATUS_ORDER[b.status] ?? 4) ||
      rank(a.impact) - rank(b.impact) ||
      mandatory(a) - mandatory(b) ||
      a.created_at.localeCompare(b.created_at) ||
      a.id.localeCompare(b.id),
  );
}

// --- answers (Story 4.7) --------------------------------------------------------------------

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "12 Oct" from a `YYYY-MM-DD` date (or an ISO timestamp's date part); the input itself when it
 * isn't one. */
export function dayMonth(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month}` : value;
}

/** "Answered by customer, 12 Oct". */
export function answeredLabel(answeredOn: string): string {
  return `Answered by customer, ${dayMonth(answeredOn)}`;
}

/** "Recorded by Jane Doe": who recorded or confirmed the answer. */
export function answerRecordedBy(answer: Pick<GapAnswer, "answered_by">): string {
  return `Recorded by ${answer.answered_by.name}`;
}

/** "Possible answer in Source 'reply.txt'": the row hint for a suggestion. */
export function possibleAnswerLabel(suggestion: Pick<AnswerSuggestion, "passage">): string {
  return `Possible answer in Source '${suggestion.passage.filename}'`;
}

/** The warning label on a suggestion whose passage reads like an instruction to the platform. */
export const INJECTION_SUSPECTED = "Injection suspected";

/** The API's longest answer, in code points (trimmed). */
export const ANSWER_MAX = 20000;

/** Why an answer text can't be recorded, or null. */
export function answerTextProblem(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return "Give the customer’s answer.";
  if (codePointLength(trimmed) > ANSWER_MAX) return "The answer can be at most 20,000 characters.";
  return null;
}

/** Why a "date answered" can't be sent, or null: required, and not after `today`. */
export function answeredOnProblem(value: string, today: string = localToday()): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Give the date the customer answered.";
  if (value > today) return "The date answered can’t be in the future.";
  return null;
}

/** What a Requirement change caused by an answer is called. */
export const REQUIREMENT_CHANGE_KINDS: Record<RequirementChangeRef["kind"], string> = {
  added: "added",
  versioned: "updated",
  pending: "pending change",
  accepted: "change accepted",
  rejected: "change rejected",
  superseded: "change superseded",
};

/** "R1 · pending change". */
export function requirementChangeLabel(change: RequirementChangeRef): string {
  return `${change.label} · ${REQUIREMENT_CHANGE_KINDS[change.kind] ?? change.kind}`;
}

/** The Requirements tab link that opens this Requirement's inspector. */
export function requirementHref(opportunityId: string, requirementId: string): string {
  return `/opportunities/${encodeURIComponent(opportunityId)}/requirements?requirement=${encodeURIComponent(requirementId)}`;
}

/** How many Gaps are open: the Gaps tab badge (Story 4.7). */
export function openGapCount(items: readonly Pick<Gap, "status">[]): number {
  return items.filter((g) => g.status === "open").length;
}

/** "2 Gaps answered, 5 open": the polite announcement after a live change (null when the
 * answered and open counts didn't change). */
export function gapsChangedAnnouncement(
  before: readonly Pick<Gap, "status">[],
  after: readonly Pick<Gap, "status">[],
): string | null {
  const answered = (items: readonly Pick<Gap, "status">[]) =>
    items.filter((g) => g.status === "answered").length;
  const open = openGapCount(after);
  if (answered(before) === answered(after) && openGapCount(before) === open) return null;
  const n = answered(after);
  return `${n} ${n === 1 ? "Gap" : "Gaps"} answered, ${open} open`;
}

// --- the Gaps tab context (Story 4.1) ---------------------------------------------------------

export const APPLICABLE_CHECKLISTS = "Applicable Checklists";
export const NO_CHECKLISTS_APPLY =
  "No Checklists apply yet — tag integration Requirements or set products and industry.";
export const SHOW_UNTAGGED = "Show them";
export const OPEN_KNOWLEDGE_SOURCES = "Open Knowledge Sources";

/** A Checklist chip: "{name} · v{version}". */
export function checklistChipLabel(checklist: Pick<GapsContextChecklist, "name" | "version">) {
  return `${checklist.name} · v${checklist.version}`;
}

/** The untagged banner, e.g. "2 integration Requirements have no Integration Type — …". */
export function untaggedBanner(n: number): string {
  const subject = n === 1 ? "integration Requirement has" : "integration Requirements have";
  return `${n} ${subject} no Integration Type — Checklists may not apply`;
}

/** Where **Show them** goes: the Requirements tab listing only the untagged ones. */
export function untaggedHref(opportunityId: string): string {
  return `/opportunities/${encodeURIComponent(opportunityId)}/requirements?untagged=integration`;
}

function counted(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The coverage banner, or null when everything in scope is documented. */
export function coverageBanner(uncovered: GapsContext["uncovered"]): string | null {
  const parts = [
    uncovered.integration_types.length > 0
      ? counted(uncovered.integration_types.length, "integration type", "integration types")
      : null,
    uncovered.products.length > 0
      ? counted(uncovered.products.length, "product", "products")
      : null,
  ].filter((part): part is string => part !== null);
  if (parts.length === 0) return null;
  return `No documentation for ${parts.join(" and ")} in scope — Gap detection may be incomplete`;
}

/** Where **Open Knowledge Sources** goes: Sources filtered by the first uncovered Integration
 * Type, or else by the first uncovered product. */
export function coverageHref(uncovered: GapsContext["uncovered"]): string {
  const type = uncovered.integration_types[0];
  if (type) return `/knowledge?integration_type=${encodeURIComponent(type.id)}`;
  const product = uncovered.products[0];
  return product ? `/knowledge?product=${encodeURIComponent(product)}` : "/knowledge";
}
