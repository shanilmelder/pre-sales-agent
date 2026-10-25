// Decision Trace display helpers (Story 9.8, demo slice). Safe on server and client.
import type { components } from "@/lib/api/client";
import { hours, roleMixLabel, ROLES, type RoleMix } from "@/lib/estimates";
import { tabHref, WORKSPACE_TABS, type WorkspaceTabSlug } from "@/lib/workspace";

export type TracePage = components["schemas"]["TracePage"];
export type TraceEvent = components["schemas"]["TraceEventItem"];
export type TraceActor = components["schemas"]["TraceActor"];
export type TraceSubject = components["schemas"]["TraceSubject"];
export type TraceOptions = components["schemas"]["TraceFilterOptions"];

export const TRACE_PAGE_SIZE = 50;
export const NO_EVENTS = "No decisions recorded yet.";
export const NO_EVENTS_TITLE = "No trace events";
export const NO_EVENTS_BODY = "Decisions and Evidence are recorded here as work happens.";
export const OPEN_OVERVIEW = "Open Overview";
export const NO_MATCHES = "No events match these filters.";
export const CLEAR_FILTERS = "Clear filters";
export const TRACE_APPEND_ONLY = "Trace rows are append-only and cannot be edited.";
export const TRACE_REASONING_NOTE =
  "Trace rows are append-only. Model reasoning is not stored, only decisions and Evidence.";
export const TRACE_LOAD_FAILED =
  "The Decision Trace could not be loaded. Try again in a moment.";

/** Each catalogued `event_type` in plain words. */
export const EVENT_LABELS: Readonly<Record<string, string>> = {
  "identity.user.provisioned": "User provisioned",
  "identity.user.role_assigned": "Role assigned",
  "identity.user.role_removed": "Role removed",
  "opportunities.opportunity.created": "Opportunity created",
  "opportunities.opportunity.updated": "Opportunity edited",
  "opportunities.collaborator.added": "Collaborator added",
  "opportunities.collaborator.removed": "Collaborator removed",
  "intake.source.added": "Source added",
  "intake.source.parsed": "Source parsed",
  "intake.source.parse_retried": "Source parse retried",
  "intake.extraction.completed": "Requirements extracted",
  "intake.requirement.edited": "Requirement edited",
  "intake.requirement.confirmed": "Requirement confirmed",
  "intake.requirement.created": "Requirement added",
  "intake.requirement.deleted": "Requirement deleted",
  "intake.requirement.split": "Requirement split",
  "intake.requirement.merged": "Requirements merged",
  "intake.requirement.integration_types_tagged": "Integration Types tagged",
  "intake.requirement_change.proposed": "Requirement change proposed",
  "intake.requirement_change.accepted": "Requirement change accepted",
  "intake.requirement_change.rejected": "Requirement change rejected",
  "gaps.gap.raised": "Gap raised",
  "gaps.clarification_question.drafted": "Clarification Question drafted",
  "gaps.clarification_question.edited": "Clarification Question edited",
  "gaps.clarification_question.approved": "Clarification Question approved",
  "gaps.detection.completed": "Gap detection completed",
  "gaps.gap.converted": "Gap converted to Assumption",
  "gaps.gap.impact_changed": "Gap impact changed",
  "gaps.gap.dismissed": "Gap dismissed",
  "gaps.gap.reopened": "Gap reopened",
  "gaps.clarification_question.exported": "Clarification Questions exported",
  "gaps.clarification_question.sent": "Clarification Question sent",
  "gaps.clarification_question.marked_unanswered": "Clarification Question marked No answer",
  "gaps.clarification_question.answered": "Clarification Question answered",
  "gaps.gap.answered": "Gap answered",
  "gaps.answer_match.suggested": "Possible answer suggested",
  "gaps.answer_match.confirmed": "Suggested answer confirmed",
  "gaps.answer_match.rejected": "Suggested answer rejected",
  "estimates.estimate_version.created": "Estimate Version created",
  "estimates.assumption.proposed": "Assumptions proposed",
  "estimates.assumption.accepted": "Assumption accepted",
  "estimates.assumption.edited": "Assumption edited",
  "estimates.risk.created": "Risk created",
  "estimates.risk.edited": "Risk edited",
  "estimates.estimate_version.exported": "Estimate exported",
  "estimates.estimate_line.edited": "Estimate line edited",
  "estimates.estimate_version.submitted": "Estimate submitted",
  "estimates.estimate_version.superseded": "Estimate Version superseded",
  "estimates.estimate_version.review_started": "Estimate review started",
  "estimates.estimate_version.review_ended": "Estimate review ended",
  "reviews.review_request.created": "Review requested",
  "reviews.review_request.cancelled": "Review Request cancelled",
  "assessments.red_team_review.completed": "Red Team Review completed",
  "assessments.critic_review.completed": "Critic Review completed",
  "assessments.finding.resolved": "Finding resolved",
  "assessments.finding.overridden": "Finding overridden",
  "assessments.assessment_run.started": "Assessment run started",
  "assessments.assessment.completed": "Assessment completed",
  "assessments.assessment_run.completed": "Assessment run completed",
  "assessments.assessment_run.cancelled": "Assessment run cancelled",
  "workflows.run.waiting_for_human": "Assessment run waiting for a decision",
  "workflows.decision.resolved": "Run decision resolved",
  "knowledge.catalogue_entry.created": "Catalogue entry created",
  "knowledge.catalogue_entry.updated": "Catalogue entry updated",
  "knowledge.catalogue_entry.retired": "Catalogue entry retired",
  "knowledge.catalogue_entry.reactivated": "Catalogue entry reactivated",
  "knowledge.checklist.published": "Checklist published",
  "knowledge.checklist.retired": "Checklist retired",
  "conflicts.conflict.detected": "Conflict detected",
  "conflicts.conflict.resolved": "Conflict resolved",
  "conflicts.conflict.escalated": "Conflict escalated",
};

/** An event type in plain words, or the raw type for one this build doesn't know. */
export function eventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] ?? eventType;
}

/** Each subject type's name and the workspace tab it lives on (null: none). */
export const SUBJECTS: Readonly<
  Record<string, { label: string; tab: WorkspaceTabSlug | null }>
> = {
  "identity.user": { label: "User", tab: null },
  "opportunities.opportunity": { label: "Opportunity", tab: "overview" },
  "intake.source": { label: "Source", tab: "sources" },
  "intake.extraction": { label: "Requirement extraction", tab: "requirements" },
  "intake.requirement": { label: "Requirement", tab: "requirements" },
  "gaps.detection": { label: "Gap detection", tab: "gaps" },
  "gaps.gap": { label: "Gap", tab: "gaps" },
  "gaps.clarification_question": {
    label: "Clarification Question",
    tab: "gaps",
  },
  "gaps.answer_match": { label: "Suggested answer", tab: "gaps" },
  "estimates.estimate_version": { label: "Estimate Version", tab: "estimate" },
  "estimates.assumption": { label: "Assumption", tab: "estimate" },
  "estimates.risk": { label: "Risk", tab: "estimate" },
  "estimates.estimate_line": { label: "Estimate line", tab: "estimate" },
  "assessments.review": { label: "Red Team Review", tab: "assessments" },
  "assessments.assessment_run": { label: "Assessment run", tab: "assessments" },
  "assessments.assessment": { label: "Assessment", tab: "assessments" },
  "knowledge.catalogue_entry": { label: "Catalogue entry", tab: null },
  "knowledge.checklist": { label: "Checklist", tab: null },
  "conflicts.conflict": { label: "Conflict", tab: "conflicts" },
  "reviews.review_request": { label: "Review Request", tab: "estimate" },
};

export function subjectLabel(subjectType: string): string {
  return SUBJECTS[subjectType]?.label ?? subjectType;
}

/** The subject as shown in a row, e.g. "Estimate Version v2". */
export function subjectText(subject: TraceSubject): string {
  const label = subjectLabel(subject.type);
  return subject.version === null ? label : `${label} v${subject.version}`;
}

/** The tab a subject links to, or null when it has none. */
export function subjectHref(
  opportunityId: string,
  subjectType: string,
): string | null {
  const tab = SUBJECTS[subjectType]?.tab ?? null;
  return tab === null ? null : tabHref(opportunityId, tab);
}

/** The inspector's link text for a subject's tab, e.g. "Open in Estimate" (null: no tab). */
export function subjectLinkText(subjectType: string): string | null {
  const tab = SUBJECTS[subjectType]?.tab ?? null;
  const label = WORKSPACE_TABS.find((t) => t.slug === tab)?.label;
  return label ? `Open in ${label}` : null;
}

/** The actor types in words (the Actor filter's options). */
export const ACTOR_TYPE_LABELS: Readonly<Record<string, string>> = {
  user: "Person",
  agent: "Agent",
  system: "System",
};

export function actorTypeLabel(actorType: string): string {
  return ACTOR_TYPE_LABELS[actorType] ?? actorType;
}

/** The actor as the inspector shows it: an agent's role with its version. */
export function actorText(actor: TraceActor): string {
  return actor.type === "agent" && actor.version
    ? `${actor.name} (v${actor.version})`
    : actor.name;
}

const FIELD_LABELS: Readonly<Record<string, string>> = {
  amount_hours: "Amount (hours)",
  char_count: "Characters",
  size_bytes: "Size (bytes)",
  version_id: "Estimate Version id",
  requirement_ids: "Requirement ids",
  into: "Split into (Requirement ids)",
  from: "Merged from",
  approved_by: "Approved by (user id)",
  before_hours: "Before (hours)",
  after_hours: "After (hours)",
  before_role_mix: "Before (role mix %)",
  after_role_mix: "After (role mix %)",
};

/** A payload field name in words: `gap_count` -> "Gap count", `line_id` -> "Line id". */
export function fieldLabel(name: string): string {
  const known = FIELD_LABELS[name];
  if (known) return known;
  const words = name.split("_").filter(Boolean).join(" ");
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
}

/** A payload value as text: null is "None", a list is comma-separated ("None" when empty),
 * a boolean is "Yes"/"No". */
export function fieldValue(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (Array.isArray(value))
    return value.length === 0 ? "None" : value.map(fieldValue).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// --- A line edit's change ------------------------------------------------------------------

export const LINE_EDITED = "estimates.estimate_line.edited";

const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

/** A role mix as the Estimate tab shows it ("E 70 · PM 20 · QA 10"), or null when the value
 * isn't an object with a number for every role in `ROLES`. */
export function roleMixText(value: unknown): string | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (!ROLES.every((role) => isNumber(record[role.value]))) return null;
  return roleMixLabel(record as RoleMix);
}

/** "12.0 h · E 70 · PM 20 · QA 10", or null when the values are missing or odd. */
function lineValues(hoursValue: unknown, mix: unknown): string | null {
  const mixText = roleMixText(mix);
  return isNumber(hoursValue) && mixText ? `${hours(hoursValue)} h · ${mixText}` : null;
}

/** A payload value as text: a `*_role_mix` field as a role mix when it is a valid one, else
 * `fieldValue`. */
export function payloadValue(name: string, value: unknown): string {
  return (name.endsWith("_role_mix") && roleMixText(value)) || fieldValue(value);
}

/** An Estimate line edit's before and after values in words, for the inspector's Change
 * section. Null for any other event, or when the payload lacks the hours or a role mix. */
export function lineEditChange(
  event: Pick<TraceEvent, "event_type" | "payload">,
): { before: string; after: string } | null {
  if (event.event_type !== LINE_EDITED) return null;
  const payload = event.payload ?? {};
  const before = lineValues(payload.before_hours, payload.before_role_mix);
  const after = lineValues(payload.after_hours, payload.after_role_mix);
  return before && after ? { before, after } : null;
}

const ABSOLUTE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

/** An ISO timestamp as "5 Oct 2026, 13:05:12 UTC", the same on server and client. */
export function absoluteTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${ABSOLUTE_FORMAT.format(date)} UTC`;
}

/** How long ago, e.g. "just now", "5 min ago", "3 h ago", "2 d ago"; older than 30 days
 * (or in the future) it is the absolute date. */
export function relativeTime(value: string, now: number = Date.now()): string {
  const at = new Date(value).getTime();
  if (Number.isNaN(at)) return value;
  const seconds = Math.floor((now - at) / 1000);
  if (seconds < -60) return absoluteTime(value);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days <= 30) return `${days} d ago`;
  return absoluteTime(value);
}

// --- URL state ------------------------------------------------------------------------------

export type TraceFilterKey = "subject" | "actor" | "event";
export type TraceFilters = Partial<Record<TraceFilterKey, string>>;
export const TRACE_FILTER_KEYS: readonly TraceFilterKey[] = [
  "subject",
  "actor",
  "event",
];
const MAX_FILTER_LENGTH = 200;

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The filters from the URL's `subject`, `actor` and `event` (blank or overlong ones are
 * ignored). */
export function parseTraceFilters(
  params: SearchParams | undefined,
): TraceFilters {
  const filters: TraceFilters = {};
  for (const key of TRACE_FILTER_KEYS) {
    const raw = first(params?.[key])?.trim();
    if (raw && raw.length <= MAX_FILTER_LENGTH) filters[key] = raw;
  }
  return filters;
}

export function hasTraceFilters(filters: TraceFilters): boolean {
  return TRACE_FILTER_KEYS.some((key) => Boolean(filters[key]));
}

/** The filters with one changed ("" clears it). */
export function withTraceFilter(
  filters: TraceFilters,
  key: TraceFilterKey,
  value: string,
): TraceFilters {
  const next = { ...filters };
  if (value) next[key] = value;
  else delete next[key];
  return next;
}

/** `/opportunities/{id}/trace` with the filters and the page (page 1 is left out). */
export function traceHref(
  opportunityId: string,
  filters: TraceFilters,
  page = 1,
): string {
  const query = new URLSearchParams();
  for (const key of TRACE_FILTER_KEYS) {
    const value = filters[key];
    if (value) query.set(key, value);
  }
  if (page > 1) query.set("page", String(page));
  const search = query.toString();
  return `${tabHref(opportunityId, "trace")}${search ? `?${search}` : ""}`;
}

/** The number of pages (at least 1). */
export function pageCount(
  page: Pick<TracePage, "total" | "page_size">,
): number {
  return Math.max(1, Math.ceil(page.total / page.page_size));
}
